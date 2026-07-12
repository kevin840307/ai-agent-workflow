#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from e2e_log_utils import copy_pruned_tree

TERMINAL_STATUSES = {"done", "failed", "cancelled", "waiting_input"}

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# This is a deterministic platform E2E, not a real-agent certification.
os.environ.setdefault("QWEN_MOCK", "1")
os.environ.setdefault("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", "0")

from app.main import app


def wait(client: TestClient, run_id: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/workflow-runs/{run_id}")
        resp.raise_for_status()
        run = resp.json()
        if run.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
            return run
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} timed out")


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "regression-workflow-e2e-logs").resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    os.environ["AIWF_STORE_FILE"] = str(output / "store.json")
    project = output / "project"
    project.mkdir()
    (project / "README.md").write_text("# Regression Workflow E2E\n", encoding="utf-8")
    requirement = (
        "WORKITEM1234 建立 Regression Test Case。SOP Block 需要 typeA/typeB 組合，"
        "一次性 SOP Definition SQL 與每次 Runtime Test Data SQL 要分開，最後用 validation.py 驗證 SUCCESS。"
    )
    with TestClient(app) as client:
        session_resp = client.post("/api/sessions", json={"title": "regression e2e", "project_path": str(project)})
        session_resp.raise_for_status()
        session = session_resp.json()
        run_resp = client.post(
            f"/api/sessions/{session['id']}/workflow-runs",
            json={
                "workflow_id": "general-auto-development",
                "project_path": str(project),
                "requirement": requirement,
                "runProfile": "small",
                "runTimeoutSec": 60,
            },
        )
        run_resp.raise_for_status()
        run = wait(client, run_resp.json()["id"])
        run_id = run["id"]
        console = client.get(f"/api/workflow-runs/{run_id}/console").json()
        artifact_index = client.get(f"/api/workflow-runs/{run_id}/artifact-index").json()
        repair = client.post("/api/small-model-repair-policy", json={"message": "validation failed", "retry_count": 1}).json()
    workspace = Path(run["workspace"])
    (output / "run-workspace.txt").write_text(str(workspace), encoding="utf-8")
    summary = {
        "status": "PASS" if run.get("status") == "done" else "FAIL",
        "agent_mode": "deterministic_mock",
        "run_id": run_id,
        "workflow": run.get("workflow_id"),
        "console_summary": console.get("summary"),
        "artifact_schema": artifact_index.get("schema"),
        "repair_policy_schema": repair.get("schema"),
        "output": str(output),
        "error": run.get("error"),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "REGRESSION_WORKFLOW_E2E_REPORT.md").write_text(
        "# Regression Workflow E2E Report\n\n"
        f"- Status: {summary['status']}\n"
        f"- Run ID: {run_id}\n"
        f"- Workflow: {run.get('workflow_id')}\n"
        f"- Agent Mode: {summary['agent_mode']} (not real-agent certification)\n"
        f"- Artifact Schema: {artifact_index.get('schema')}\n"
        f"- Error: {run.get('error') or '-'}\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
