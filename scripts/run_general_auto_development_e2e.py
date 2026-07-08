from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from e2e_log_utils import copy_pruned_tree, iter_project_snapshot_files

TERMINAL_STATUSES = {"done", "failed", "cancelled", "waiting_input"}


def wait_for_terminal_run(client: TestClient, run: dict, timeout_sec: float = 60.0) -> dict:
    """Wait for a terminal run.

    Prefer reading the isolated test store directly after the API creates the
    run.  This avoids TestClient/background-task shutdown edge cases in local
    E2E scripts while still exercising the API to start the workflow.
    """
    deadline = time.time() + timeout_sec
    run_id = run["id"]
    store_file = Path(os.environ.get("AIWF_STORE_FILE", ""))
    while time.time() < deadline:
        current = None
        if store_file.exists():
            try:
                data = json.loads(store_file.read_text(encoding="utf-8-sig"))
                current = next((item for item in data.get("runs", []) if item.get("id") == run_id), None)
            except Exception:
                current = None
        if current is not None and current.get("status") in TERMINAL_STATUSES:
            return current
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_sec}s")

def copy_run_logs(project_dir: Path, run: dict, output_root: Path, label: str) -> None:
    dest = output_root / label
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    (dest / "workspace.txt").write_text(str(run.get("workspace") or ""), encoding="utf-8")
    timeline = "\n".join(f"{item.get('created_at','')} {item.get('message','')}" for item in run.get("timeline", []))
    (dest / "timeline.txt").write_text(timeline + "\n", encoding="utf-8")
    steps = [
        {
            "key": step.get("key"),
            "status": step.get("status"),
            "error": step.get("error"),
            "retry_count": step.get("retry_count") or step.get("retryCount"),
        }
        for step in run.get("steps", [])
    ]
    (dest / "steps.json").write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")

def create_project(root: Path, *, with_validation: bool) -> Path:
    project_dir = root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# General Auto Development Mock Project\n", encoding="utf-8")
    if with_validation:
        (project_dir / "validation.py").write_text(
            "from workflow_mock_feature import workflow_greeting\n"
            "assert workflow_greeting() == 'hello from controlled workflow'\n"
            "print('external validation ok')\n",
            encoding="utf-8",
        )
    return project_dir


def run_case(client: TestClient, output_root: Path, label: str, *, scenario: str, with_validation: bool) -> dict:
    os.environ["QWEN_MOCK_SCENARIO"] = scenario
    project_dir = create_project(output_root / "projects" / label, with_validation=with_validation)
    session_resp = client.post("/api/sessions", json={"title": f"general e2e {label}", "project_path": str(project_dir)})
    session_resp.raise_for_status()
    session = session_resp.json()
    run_resp = client.post(
        f"/api/sessions/{session['id']}/workflow-runs",
        json={
            "workflow_id": "general-auto-development",
            "project_path": str(project_dir),
            "requirement": "Create a deterministic Python helper named workflow_greeting and verify it with tests.",
            "test_command": "python -c \"from workflow_mock_feature import workflow_greeting; assert workflow_greeting() == \\\"hello from controlled workflow\\\"\"",
        },
    )
    run_resp.raise_for_status()
    run = wait_for_terminal_run(client, run_resp.json())
    print(f"copying {label}...", flush=True)
    copy_run_logs(project_dir, run, output_root, label)
    print(f"copied {label}", flush=True)
    return {"case": label, "status": run.get("status"), "error": run.get("error"), "workspace": run.get("workspace")}


def _parse_output_root(default: str) -> Path:
    parser = argparse.ArgumentParser(description="Run workflow E2E scenarios and export logs.")
    parser.add_argument("output", nargs="?", help="Output directory (legacy positional).")
    parser.add_argument("--output", dest="output_option", help="Output directory.")
    args = parser.parse_args()
    return Path(args.output_option or args.output or default).resolve()


def main() -> int:
    output_root = _parse_output_root("general-auto-development-e2e-logs")
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
    os.environ["AIWF_STORE_FILE"] = str(output_root / "store.json")

    from app.main import app

    cases = [
        ("01-normal-no-validation", "", False),
        ("02-execute-no-files-retry", "general_no_files_once", False),
        ("03-review-fail-repair", "general_review_fail_once", False),
        ("04-validation-fail-repair", "general_validation_fail_once", True),
    ]
    results: list[dict] = []
    # Keep each scenario in a fresh TestClient to avoid long-lived background
    # task/TestClient state carrying over between intentionally failing/retrying
    # workflow cases.
    for label, scenario, with_validation in cases:
        print(f"running {label}...", flush=True)
        with TestClient(app) as client:
            results.append(run_case(client, output_root, label, scenario=scenario, with_validation=with_validation))
        print(f"done {label}: {results[-1].get('status')}", flush=True)

    summary = {"status": "PASS" if all(item["status"] == "done" for item in results) else "FAIL", "results": results}
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
