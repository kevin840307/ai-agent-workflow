from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
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
            self.assertEqual(template.json()["template_id"], "regression-test-case-generation")
            self.assertEqual(template.json()["workflow_id"], "general-auto-development")
            self.assertIn("runtime-test-data.sql", template.json()["outputs"])

            repair = client.post("/api/small-model-repair-policy", json={"message": "No files changed under Project Path", "retry_count": 3})
            self.assertEqual(repair.status_code, 200, repair.text)
            self.assertEqual(repair.json()["failure"]["code"], "NO_FILE_CHANGE")
            self.assertEqual(repair.json()["escalation"], "replan_or_split_task")

            matrix = client.post(
                "/api/real-agent-matrix",
                json={"agents": ["qwen"], "workflows": ["general-auto-development"], "cases": ["sort"], "mode": "self-prompt-test"},
            )
            self.assertEqual(matrix.status_code, 200, matrix.text)
            self.assertEqual(matrix.json()["schema"], "aiwf.real-agent-matrix.v4")
            self.assertIn("--self-prompt-test", matrix.json()["rows"][0]["command"])

    def test_product_workflow_runs_and_writes_compact_artifact_index(self) -> None:
        """The product exposes only the three approved workflows.

        Regression-template APIs remain available for plugin/tooling use, but they are
        not runnable product workflow assets.  This integration check therefore uses
        the default General workflow and verifies the compact evidence index.
        """
        with patch.dict(os.environ, {"QWEN_MOCK": "1"}), TemporaryDirectory() as tmp, TestClient(app) as client:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "README.md").write_text("# Project\n", encoding="utf-8")
            session = client.post("/api/sessions", json={"title": "general", "project_path": str(project)})
            self.assertEqual(session.status_code, 200, session.text)
            run_resp = client.post(
                f"/api/sessions/{session.json()['id']}/workflow-runs",
                json={
                    "workflow_id": "general-auto-development",
                    "project_path": str(project),
                    "requirement": "Create a small Python add(a, b) function and deterministic tests.",
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
                if current.get("status") in {"done", "failed", "cancelled", "waiting_input", "blocked"}:
                    break
                time.sleep(0.1)
            self.assertEqual(current.get("status"), "done", current.get("error"))
            workspace = Path(current["workspace"])
            self.assertTrue((workspace / ".workflow/artifacts/index.json").exists())
            artifact_index = client.get(f"/api/workflow-runs/{run_id}/artifact-index")
            self.assertEqual(artifact_index.status_code, 200, artifact_index.text)
            self.assertEqual(artifact_index.json()["schema"], ARTIFACT_SCHEMA)
            self.assertGreaterEqual(artifact_index.json()["summary"]["steps_total"], 1)
            console = client.get(f"/api/workflow-runs/{run_id}/console")
            self.assertEqual(console.status_code, 200, console.text)
            self.assertEqual(console.json()["summary"]["steps_attention"], 0)

    def test_ui_has_run_detail_and_artifact_index(self) -> None:
        html = Path("static/index.html").read_text(encoding="utf-8")
        js = Path("static/js/features/runs.js").read_text(encoding="utf-8")
        self.assertIn("Run Center", html)
        self.assertIn("overviewPanel", html)
        self.assertIn("diagnosticsDrawer", html)
        self.assertIn("/overview", js)
        self.assertNotIn("runDetailPanel", html)
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
        self.assertIn('"schema": "aiwf.real-agent-matrix.v4"', proc.stdout)
        matrix_source = Path("scripts/run_real_agent_matrix.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--resume"', matrix_source)
        self.assertIn('existing.get("schema") == "aiwf.real-agent-acceptance-cell.v1"', matrix_source)
        self.assertIn('existing.get("run_status") == "done"', matrix_source)
        self.assertIn('external_validation_passed', matrix_source)


if __name__ == "__main__":
    unittest.main()
