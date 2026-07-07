#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF_PROMPT = ROOT / "scripts" / "run_self_prompt_workflow_e2e.py"


def _count_files(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _run_once(output_dir: Path, workflow: str, timeout_sec: float) -> dict:
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(SELF_PROMPT), str(output_dir), "--workflow", workflow, "--timeout-sec", str(timeout_sec)],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=max(timeout_sec + 30, 45),
    )
    elapsed = time.monotonic() - start
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    project_path = Path(summary.get("results", [{}])[0].get("project_path", "")) if summary.get("results") else Path()
    workspace = Path(summary.get("results", [{}])[0].get("workspace", "")) if summary.get("results") else Path()
    lock_exists = any((project_path / candidate / "project-run-lock.json").exists() for candidate in [".ai-workflow", ".qwen-workflow"])
    return {
        "status": "PASS" if proc.returncode == 0 and summary.get("status") == "PASS" and not lock_exists else "FAIL",
        "returncode": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "summary_status": summary.get("status"),
        "project_path": str(project_path),
        "workspace": str(workspace),
        "project_lock_leftover": lock_exists,
        "workspace_file_count": _count_files(workspace),
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
    }


def render_report(report: dict) -> str:
    lines = [
        "# AI Workflow Soak Test Report",
        "",
        f"Status: **{report['status']}**",
        f"Runs: {report['runs']}",
        f"Workflow: `{report['workflow']}`",
        "",
        "| # | Status | Seconds | Files | Lock leftover |",
        "|---:|---|---:|---:|---|",
    ]
    for index, item in enumerate(report["results"], start=1):
        lines.append(f"| {index} | {item['status']} | {item['elapsed_seconds']} | {item['workspace_file_count']} | {item['project_lock_leftover']} |")
    if report.get("failures"):
        lines.extend(["", "## Failures"])
        for failure in report["failures"]:
            lines.append(f"- run {failure['index']}: {failure.get('stdout_tail') or failure.get('stderr_tail') or 'no output'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated self-prompt workflows to detect lock/artifact leaks.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--workflow", default="general-auto-development", choices=["general-auto-development", "adaptive-auto-workflow"])
    parser.add_argument("--output", default="soak-test-output")
    parser.add_argument("--timeout-sec", type=float, default=80)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    for index in range(1, args.runs + 1):
        run_output = output / f"run-{index:03d}"
        item = _run_once(run_output, args.workflow, args.timeout_sec)
        results.append(item)
        if item["status"] != "PASS":
            failures.append({"index": index, **item})
            break
    report = {
        "schema": "aiwf.soak-test.v1",
        "status": "PASS" if not failures and len(results) == args.runs else "FAIL",
        "runs": args.runs,
        "workflow": args.workflow,
        "results": results,
        "failures": failures,
    }
    (output / "soak-summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "soak-test-report.md").write_text(render_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
