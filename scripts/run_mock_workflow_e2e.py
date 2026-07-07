from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from e2e_log_utils import iter_project_snapshot_files


def wait_for_terminal_run(client: TestClient, run: dict, timeout_sec: float = 30.0) -> dict:
    deadline = time.time() + timeout_sec
    run_id = run["id"]
    while time.time() < deadline:
        response = client.get(f"/api/workflow-runs/{run_id}")
        response.raise_for_status()
        current = response.json()
        if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
            return current
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_sec}s")


def copy_run_logs(project_dir: Path, run: dict, output_root: Path, label: str) -> None:
    dest = output_root / label
    dest.mkdir(parents=True, exist_ok=True)
    workspace = Path(run["workspace"])
    if workspace.exists():
        shutil.copytree(workspace, dest / "run-workspace", dirs_exist_ok=True)
    project_snapshot = dest / "project-snapshot"
    project_snapshot.mkdir(parents=True, exist_ok=True)
    for path in iter_project_snapshot_files(project_dir):
        rel = path.relative_to(project_dir)
        target = project_snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (dest / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
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


def run_workflow(client: TestClient, workflow_id: str, project_dir: Path) -> dict:
    session_resp = client.post("/api/sessions", json={"title": f"mock {workflow_id}", "project_path": str(project_dir)})
    session_resp.raise_for_status()
    session = session_resp.json()
    run_resp = client.post(
        f"/api/sessions/{session['id']}/workflow-runs",
        json={
            "workflow_id": workflow_id,
            "project_path": str(project_dir),
            "requirement": "Create a deterministic Python helper named workflow_greeting and verify it with tests.",
            "test_command": "python -c \"from workflow_mock_feature import workflow_greeting; assert workflow_greeting() == \\\"hello from controlled workflow\\\"\"",
        },
    )
    run_resp.raise_for_status()
    return wait_for_terminal_run(client, run_resp.json())


def main() -> int:
    output_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("mock-e2e-logs")
    output_root = output_root.resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"

    store_file = output_root / "store.json"
    os.environ["AIWF_STORE_FILE"] = str(store_file)

    # Import after environment variables are set so runtime uses the temporary store.
    from app.main import app

    results: list[dict] = []
    for workflow_id in ["adaptive-auto-workflow", "general-auto-development"]:
        with TestClient(app) as client:
            project_dir = output_root / "projects" / workflow_id
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "README.md").write_text(f"# Mock project for {workflow_id}\n", encoding="utf-8")
            run = run_workflow(client, workflow_id, project_dir)
            copy_run_logs(project_dir, run, output_root, workflow_id)
            results.append({"workflow_id": workflow_id, "status": run.get("status"), "error": run.get("error"), "workspace": run.get("workspace")})

    summary = {"status": "PASS" if all(r["status"] == "done" for r in results) else "FAIL", "results": results}
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
