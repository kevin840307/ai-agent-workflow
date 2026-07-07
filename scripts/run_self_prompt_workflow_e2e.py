from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from e2e_log_utils import iter_project_snapshot_files

from app.testing.self_prompt_sorting_agent import SORT_FUNCTIONS, SORTING_PROMPT, validation_script
from app.workflow_runtime.stability_score import compute_workflow_stability_score, write_stability_report

TERMINAL_STATUSES = {"done", "failed", "cancelled", "waiting_input"}


def wait_for_terminal_run(client: TestClient, run: dict[str, Any], timeout_sec: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    run_id = run["id"]
    while time.time() < deadline:
        response = client.get(f"/api/workflow-runs/{run_id}")
        response.raise_for_status()
        current = response.json()
        if current.get("status") in TERMINAL_STATUSES:
            return current
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_sec}s")


def configure_env(output_root: Path) -> None:
    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_MOCK_SCENARIO"] = "self_prompt_sorting_algorithms"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
    os.environ.setdefault("WORKFLOW_TEST_TIMEOUT_SEC", "20")
    os.environ["AIWF_STORE_FILE"] = str(output_root / "store.json")


def create_project(output_root: Path, workflow_id: str) -> Path:
    project_dir = output_root / "projects" / workflow_id / "project"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text(
        "# Self-Prompt Sorting Workflow E2E\n\n"
        f"Workflow: `{workflow_id}`\n\n"
        f"Prompt: `{SORTING_PROMPT}`\n",
        encoding="utf-8",
    )
    (project_dir / "validation.py").write_text(validation_script(), encoding="utf-8")
    return project_dir


def copy_run_logs(project_dir: Path, run: dict[str, Any], output_root: Path, workflow_id: str) -> None:
    dest = output_root / workflow_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    workspace = Path(run.get("workspace") or "")
    if workspace.exists():
        shutil.copytree(workspace, dest / "run-workspace", dirs_exist_ok=True)

    project_snapshot = dest / "project-snapshot"
    project_snapshot.mkdir(parents=True, exist_ok=True)
    for path in iter_project_snapshot_files(project_dir):
        rel = path.relative_to(project_dir)
        target = project_snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


    timeline_lines = []
    for item in run.get("timeline", []):
        stamp = item.get("time") or item.get("created_at") or ""
        kind = item.get("kind") or item.get("type") or ""
        message = item.get("message") or item.get("text") or ""
        timeline_lines.append(f"{stamp} {kind} {message}".strip())
    (dest / "timeline.txt").write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")

    step_rows = []
    for step in run.get("steps", []):
        step_rows.append(
            {
                "key": step.get("key"),
                "name": step.get("name"),
                "status": step.get("status"),
                "error": step.get("error"),
                "retry_count": step.get("retry_count") or step.get("retryCount") or 0,
            }
        )
    (dest / "steps.json").write_text(json.dumps(step_rows, indent=2, ensure_ascii=False), encoding="utf-8")


def run_manual_validation(project_dir: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "validation.py"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def artifact_checks(project_dir: Path, run: dict[str, Any]) -> dict[str, Any]:
    source_path = project_dir / "sorting_algorithms.py"
    tests_path = project_dir / "tests" / "test_sorting_algorithms.py"
    validation = run_manual_validation(project_dir)
    output_dir = Path(run.get("workspace") or "") / "output"
    external_validation = ""
    for candidate in [output_dir / "external-validation-result.md", output_dir / "python-gate-result.md"]:
        if candidate.exists():
            external_validation += candidate.read_text(encoding="utf-8") + "\n"
    source_text = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
    return {
        "source_exists": source_path.exists(),
        "tests_exist": tests_path.exists(),
        "all_functions_present": all(f"def {name}" in source_text for name in SORT_FUNCTIONS),
        "manual_validation_returncode": validation["returncode"],
        "manual_validation_stdout": validation["stdout"].strip(),
        "manual_validation_stderr": validation["stderr"].strip(),
        "workflow_validation_has_pass": "Status: PASS" in external_validation or "Exit Code: 0" in external_validation or "ExitCode: 0" in external_validation,
        "workflow_validation_excerpt": external_validation[:1200],
    }


def run_workflow_case(client: TestClient, output_root: Path, workflow_id: str, timeout_sec: float) -> dict[str, Any]:
    project_dir = create_project(output_root, workflow_id)
    session_response = client.post(
        "/api/sessions",
        json={"title": f"self-prompt sorting {workflow_id}", "project_path": str(project_dir)},
    )
    session_response.raise_for_status()
    session = session_response.json()
    payload = {
        "workflow_id": workflow_id,
        "project_path": str(project_dir),
        "requirement": SORTING_PROMPT,
        "validation_script": "validation.py",
        "test_command": f"{sys.executable} validation.py",
        "agent": "qwen",
        "runProfile": "small",
    }
    run_response = client.post(f"/api/sessions/{session['id']}/workflow-runs", json=payload)
    run_response.raise_for_status()
    run = wait_for_terminal_run(client, run_response.json(), timeout_sec=timeout_sec)
    copy_run_logs(project_dir, run, output_root, workflow_id)
    checks = artifact_checks(project_dir, run)
    result = {
        "workflow_id": workflow_id,
        "status": run.get("status"),
        "error": run.get("error"),
        "run_id": run.get("id"),
        "workspace": run.get("workspace"),
        "project_path": str(project_dir),
        "steps": [
            {
                "key": step.get("key"),
                "status": step.get("status"),
                "retry_count": step.get("retry_count") or step.get("retryCount") or 0,
                "error": step.get("error"),
            }
            for step in run.get("steps", [])
        ],
        "checks": checks,
    }
    result["stability"] = compute_workflow_stability_score(run, checks)
    (output_root / workflow_id / "case-summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_stability_report(output_root / workflow_id / "stability-report.md", workflow_id, result)
    return result


def render_console_log(summary: dict[str, Any]) -> str:
    lines = [
        "# Self-Prompt Workflow E2E Console Log",
        "",
        f"Prompt: {SORTING_PROMPT}",
        f"Overall Status: {summary['status']}",
        "",
    ]
    for result in summary["results"]:
        lines.extend(
            [
                f"## {result['workflow_id']}",
                f"- Run ID: {result.get('run_id')}",
                f"- Status: {result.get('status')}",
                f"- Project: {result.get('project_path')}",
                f"- Workspace: {result.get('workspace')}",
                f"- Manual validation: rc={result['checks'].get('manual_validation_returncode')} stdout={result['checks'].get('manual_validation_stdout')}",
                f"- Stability: {result.get('stability', {}).get('score')} / 100 risk={result.get('stability', {}).get('risk')}",
                "- Steps:",
            ]
        )
        for step in result.get("steps", []):
            err = f" error={step.get('error')}" if step.get("error") else ""
            lines.append(f"  - {step.get('key')}: {step.get('status')} retry={step.get('retry_count')}{err}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run self-prompt sorting E2E through General and Adaptive workflow APIs.")
    parser.add_argument("output", nargs="?", default="self-prompt-workflow-e2e-logs")
    parser.add_argument("--timeout-sec", type=float, default=90.0)
    parser.add_argument(
        "--workflow",
        choices=["all", "general-auto-development", "adaptive-auto-workflow"],
        default="all",
        help="Run one workflow or both workflows.",
    )
    args = parser.parse_args()

    output_root = Path(args.output).resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    configure_env(output_root)

    workflows = ["general-auto-development", "adaptive-auto-workflow"] if args.workflow == "all" else [args.workflow]

    from app.main import app

    results: list[dict[str, Any]] = []
    with TestClient(app) as client:
        for workflow_id in workflows:
            result = run_workflow_case(client, output_root, workflow_id, timeout_sec=args.timeout_sec)
            print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
            results.append(result)

    def passed(result: dict[str, Any]) -> bool:
        checks = result.get("checks") or {}
        return (
            result.get("status") == "done"
            and checks.get("source_exists")
            and checks.get("tests_exist")
            and checks.get("all_functions_present")
            and checks.get("manual_validation_returncode") == 0
            and checks.get("workflow_validation_has_pass")
        )

    summary = {
        "status": "PASS" if all(passed(item) for item in results) else "FAIL",
        "prompt": SORTING_PROMPT,
        "agent_mode": "self_prompt_qwen_mock",
        "results": results,
        "output_root": str(output_root),
    }
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_root / "workflow-console.log").write_text(render_console_log(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
