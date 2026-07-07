from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.workflow_runtime.repair_policy import policy_for_failure, render_repair_prompt
from app.workflow_runtime.run_artifacts import ARTIFACT_SCHEMA


class NextRoundFeatureTests(unittest.TestCase):
    def test_runtime_architecture_facades_and_repair_policy(self) -> None:
        from app.workflow_runtime.execution import WorkflowExecutor
        from app.workflow_runtime.retry import policy_for_failure as retry_policy_for_failure
        from app.workflow_runtime.observability import read_run_artifact_index

        self.assertIsNotNone(WorkflowExecutor)
        self.assertIs(retry_policy_for_failure, policy_for_failure)
        self.assertTrue(callable(read_run_artifact_index))
        policy = policy_for_failure("validation.py failed with AssertionError", step_key="run_external_validation", retry_count=2)
        self.assertEqual(policy["schema"], "aiwf.small-model-repair-policy.v1")
        self.assertEqual(policy["failure"]["code"], "VALIDATION_FAILED")
        self.assertIn("validation.py", render_repair_prompt(policy))

    def test_productization_endpoints_for_regression_repair_and_matrix(self) -> None:
        with TestClient(app) as client:
            template = client.get("/api/regression-workflow/template")
            self.assertEqual(template.status_code, 200, template.text)
            self.assertEqual(template.json()["workflow_id"], "regression-test-case-generation")
            self.assertIn("runtime-test-data.sql", template.json()["outputs"])

            repair = client.post("/api/small-model-repair-policy", json={"message": "No files changed under Project Path", "retry_count": 3})
            self.assertEqual(repair.status_code, 200, repair.text)
            self.assertEqual(repair.json()["failure"]["code"], "NO_FILE_CHANGE")
            self.assertEqual(repair.json()["escalation"], "replan_or_split_task")

            matrix = client.post(
                "/api/real-agent-matrix",
                json={"agents": ["qwen"], "workflows": ["regression-test-case-generation"], "cases": ["sort"], "mode": "self-prompt-test"},
            )
            self.assertEqual(matrix.status_code, 200, matrix.text)
            self.assertEqual(matrix.json()["schema"], "aiwf.real-agent-matrix.v2")
            self.assertIn("--self-prompt-test", matrix.json()["rows"][0]["command"])

    def test_regression_workflow_runs_and_writes_standard_artifact_index(self) -> None:
        with TemporaryDirectory() as tmp, TestClient(app) as client:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            session = client.post("/api/sessions", json={"title": "regression", "project_path": str(project)})
            self.assertEqual(session.status_code, 200, session.text)
            run_resp = client.post(
                f"/api/sessions/{session.json()['id']}/workflow-runs",
                json={
                    "workflow_id": "regression-test-case-generation",
                    "project_path": str(project),
                    "requirement": "WORKITEM5678 typeA/typeB 組合，產出 SOP SQL、Runtime SQL、validation.py、Markdown case。",
                    "runProfile": "small",
                    "runTimeoutSec": 60,
                },
            )
            self.assertEqual(run_resp.status_code, 200, run_resp.text)
            run_id = run_resp.json()["id"]
            deadline = time.time() + 70
            current = run_resp.json()
            while time.time() < deadline:
                current = client.get(f"/api/workflow-runs/{run_id}").json()
                if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
                    break
                time.sleep(0.1)
            self.assertEqual(current.get("status"), "done", current.get("error"))
            workspace = Path(current["workspace"])
            for rel in [
                "output/sop-definition.sql",
                "output/runtime-test-data.sql",
                "output/validation.py",
                "output/regression-test-case.md",
                "output/dry-run-report.md",
                ".workflow/artifacts/index.json",
            ]:
                self.assertTrue((workspace / rel).exists(), rel)
            artifact_index = client.get(f"/api/workflow-runs/{run_id}/artifact-index")
            self.assertEqual(artifact_index.status_code, 200, artifact_index.text)
            self.assertEqual(artifact_index.json()["schema"], ARTIFACT_SCHEMA)
            self.assertGreaterEqual(artifact_index.json()["summary"]["steps_total"], 7)
            console = client.get(f"/api/workflow-runs/{run_id}/console")
            self.assertEqual(console.json()["summary"]["steps_attention"], 0)

    def test_ui_has_run_detail_and_artifact_index(self) -> None:
        html = Path("static/index.html").read_text(encoding="utf-8")
        js = Path("static/js/features/runs.js").read_text(encoding="utf-8")
        self.assertIn(">Detail</button>", html)
        self.assertIn("runDetailPanel", html)
        self.assertIn("Artifact Index", js)
        self.assertIn("/artifact-index", js)
        self.assertIn("/repair-policy", Path("app/api/routes/workflow_runs.py").read_text(encoding="utf-8"))

    def test_real_agent_matrix_cli_safe_execute(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_real_agent_matrix.py",
                "--agent",
                "qwen",
                "--workflow",
                "adaptive-auto-workflow",
                "--case",
                "sort",
                "--mode",
                "self-prompt-test",
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn('"schema": "aiwf.real-agent-matrix.v2"', proc.stdout)


if __name__ == "__main__":
    unittest.main()
