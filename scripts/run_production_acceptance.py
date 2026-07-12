#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from app.agents.process_supervisor import terminate_popen_tree

DEFAULT_OUTPUT = REPO_ROOT / "reports" / "production-acceptance"


def run_cmd(name: str, cmd: list[str], *, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    returncode = 0
    with tempfile.TemporaryDirectory(prefix="aiwf-acceptance-") as tmp:
        stdout_path = Path(tmp) / "stdout.log"
        stderr_path = Path(tmp) / "stderr.log"
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_file, stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file:
            process = subprocess.Popen(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")},
                start_new_session=(os.name != "nt"),
            )
            while True:
                returncode = process.poll()
                if returncode is not None:
                    break
                if time.monotonic() - started > timeout:
                    timed_out = True
                    terminate_popen_tree(process, grace_sec=2.0)
                    returncode = 124
                    break
                time.sleep(0.1)
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    return {
        "name": name,
        "command": " ".join(cmd),
        "returncode": returncode,
        "status": "PASS" if returncode == 0 else "FAIL",
        "timed_out": timed_out,
        "duration_sec": round(time.monotonic() - started, 2),
        "stdout_tail": "\n".join(stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(stderr.splitlines()[-80:]),
    }


def node_check_commands() -> list[list[str]]:
    paths = sorted((REPO_ROOT / "static" / "js").rglob("*.js"))
    if not paths:
        return []
    return [["node", "--check", str(path.relative_to(REPO_ROOT))] for path in paths]




def browser_smoke_command() -> list[str]:
    command = [sys.executable, "scripts/run_browser_ui_smoke.py"]
    executable = os.environ.get("AIWF_BROWSER_EXECUTABLE") or next(
        (path for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable") if (path := shutil.which(name))),
        None,
    )
    try:
        import playwright  # type: ignore  # noqa: F401
    except Exception:
        return command
    if executable:
        command.append("--browser")
    return command

def render_report(result: dict[str, Any]) -> str:
    status = result["status"]
    lines = [
        "# Production Acceptance Report",
        "",
        f"Schema: `{result['schema']}`",
        f"Status: **{status}**",
        f"Generated: {result['generated_at']}",
        "",
        "## Gate Result",
        "",
        "| Check | Status | Duration |",
        "|---|---:|---:|",
    ]
    for check in result["checks"]:
        lines.append(f"| `{check['name']}` | {check['status']} | {check['duration_sec']}s |")
    lines.extend([
        "",
        "## Production Recommendation",
        "",
    ])
    if status == "PASS":
        lines.extend([
            "- Controlled internal pilot: **OK**.",
            "- Team beta with patch review: **OK after real-agent matrix evidence is collected**.",
            "- Full production auto-apply: **not recommended unless Store backend, auth, audit, and real-agent pass rate are production-proven**.",
        ])
    else:
        lines.append("- Production gate failed. Fix failed checks before pilot promotion.")
    lines.extend(["", "## Failed Check Details", ""])
    failures = [check for check in result["checks"] if check["status"] != "PASS"]
    if not failures:
        lines.append("No failed checks.")
    for check in failures:
        lines.extend([
            f"### {check['name']}",
            "",
            "```text",
            check.get("stdout_tail", ""),
            check.get("stderr_tail", ""),
            "```",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AI Workflow production acceptance gates.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output directory for reports")
    parser.add_argument("--quick", action="store_true", help="Skip long CI matrix and E2E checks")
    parser.add_argument("--soak-runs", type=int, default=2, help="Soak runs when not quick")
    args = parser.parse_args()

    checks: list[dict[str, Any]] = []
    checks.append(run_cmd("compileall", [sys.executable, "-m", "compileall", "app", "tests", "scripts", "-q"], timeout=120))
    for index, cmd in enumerate(node_check_commands(), start=1):
        checks.append(run_cmd(f"node-check-{index}", cmd, timeout=30))
    checks.append(run_cmd("workflow-assets", [sys.executable, "scripts/validate_workflow_assets.py"], timeout=120))
    checks.append(run_cmd("browser-ui-smoke", browser_smoke_command(), timeout=120))
    checks.append(run_cmd("crash-recovery-simulation", [sys.executable, "scripts/run_crash_recovery_test.py", "--output", str(Path(args.output) / "crash-recovery")], timeout=120))
    checks.append(run_cmd(
        "agent-slash-command-routes",
        [
            sys.executable,
            "-c",
            (
                "import json,tempfile; from pathlib import Path; "
                "from scripts.install_agent_commands import verify_command_routes; "
                "d=tempfile.TemporaryDirectory(); "
                "print(json.dumps(verify_command_routes(project=Path(d.name)), ensure_ascii=False)); "
                "d.cleanup()"
            ),
        ],
        timeout=120,
    ))
    if not args.quick:
        for test_file in (
            "tests/test_production_hardening_round2.py",
            "tests/test_production_hardening_round3.py",
            "tests/test_reliability_hardening_round5.py",
            "tests/test_unattended_stability_v16.py",
            "tests/test_v17_runtime_ui_regressions.py",
        ):
            checks.append(run_cmd(f"pytest-{Path(test_file).stem}", [sys.executable, "-m", "pytest", "-q", test_file], timeout=180))
        checks.append(run_cmd("ci-matrix-all-isolated", [sys.executable, "scripts/run_tests.py", "--mode", "all", "--isolate-all", "--file-timeout", "240"], timeout=2400))
        checks.append(run_cmd("self-prompt-e2e", [sys.executable, "scripts/run_self_prompt_workflow_e2e.py", str(Path(args.output) / "self-prompt")], timeout=300))
        checks.append(run_cmd("regression-workflow-e2e", [sys.executable, "scripts/run_regression_workflow_e2e.py", str(Path(args.output) / "regression")], timeout=300))
        checks.append(run_cmd("soak-test", [sys.executable, "scripts/run_soak_test.py", "--runs", str(max(1, args.soak_runs)), "--output", str(Path(args.output) / "soak")], timeout=600))
        checks.append(run_cmd("cleanup-dry-run", [sys.executable, "-c", "import asyncio; from app.services.maintenance_service import cleanup_runs; print(asyncio.run(cleanup_runs(dry_run=True)))"], timeout=120))

    result = {
        "schema": "aiwf.production-acceptance.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL",
        "checks": checks,
    }
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "production-acceptance-report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    report_md = render_report(result)
    (out / "production-acceptance-report.md").write_text(report_md, encoding="utf-8")
    print(report_md)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
