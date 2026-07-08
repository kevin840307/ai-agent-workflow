#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "production-acceptance"


def run_cmd(name: str, cmd: list[str], *, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")},
    )
    return {
        "name": name,
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "duration_sec": round(time.monotonic() - started, 2),
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-80:]),
    }


def node_check_commands() -> list[list[str]]:
    paths = sorted((REPO_ROOT / "static" / "js").rglob("*.js"))
    if not paths:
        return []
    return [["node", "--check", str(path.relative_to(REPO_ROOT))] for path in paths]


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
    checks.append(run_cmd("browser-ui-smoke", [sys.executable, "scripts/run_browser_ui_smoke.py"], timeout=60))
    checks.append(run_cmd("crash-recovery-simulation", [sys.executable, "scripts/run_crash_recovery_test.py"], timeout=120))
    if not args.quick:
        checks.append(run_cmd("pytest-targeted-hardening", [sys.executable, "-m", "pytest", "-q", "tests/test_production_hardening_round2.py", "tests/test_production_hardening_round3.py", "tests/test_reliability_hardening_round5.py"], timeout=300))
        checks.append(run_cmd("ci-matrix-fast", [sys.executable, "scripts/run_tests.py", "--mode", "fast", "--execute-all"], timeout=900))
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
