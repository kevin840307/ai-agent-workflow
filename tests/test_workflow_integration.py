from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules import api as runtime
from app.services import workflow_config_service


MINIMAL_WORKFLOW = {
    "id": "integration-minimal",
    "kind": "custom",
    "name": "Integration Minimal",
    "folderName": "system-controlled-qwen",
    "skillRoot": "",
    "steps": [
        {
            "id": "int-generate-spec",
            "key": "generate_spec",
            "name": "Generate Spec",
            "type": "ai",
            "templatePath": "prompts/01_spec.md",
            "filename": "spec.md",
            "outputFile": "spec.md",
            "maxRetries": 1,
            "allowInteraction": False,
            "expectedFiles": ["spec.md"],
        },
        {
            "id": "int-validate-spec",
            "key": "validate_spec",
            "name": "Validate Spec",
            "type": "validation",
            "function": "validate_spec",
            "maxRetries": 1,
            "retryFromStepKey": "generate_spec",
        },
        {
            "id": "int-generate-todo",
            "key": "generate_todo",
            "name": "Generate Todo",
            "type": "ai",
            "templatePath": "prompts/03_todo.md",
            "filename": "todo.md",
            "outputFile": "todo.md",
            "maxRetries": 1,
            "allowInteraction": False,
            "expectedFiles": ["todo.md"],
        },
        {
            "id": "int-validate-todo",
            "key": "validate_todo",
            "name": "Validate Todo",
            "type": "validation",
            "function": "validate_todo",
            "maxRetries": 1,
            "retryFromStepKey": "generate_todo",
        },
    ],
}


class WorkflowIntegrationTests(unittest.TestCase):
    def _wait_for_terminal_run(self, client: TestClient, run: dict, timeout_sec: float = 10) -> dict:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            latest = client.get(f"/api/workflow-runs/{run['id']}")
            self.assertEqual(latest.status_code, 200, latest.text)
            run = latest.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                cleanup_deadline = time.time() + 2
                while time.time() < cleanup_deadline:
                    task = runtime.running_tasks.get(run["id"])
                    if task is None or task.done():
                        return run
                    time.sleep(0.01)
                return run
            time.sleep(0.1)
        return run

    def test_minimal_workflow_run_completes_and_artifacts_are_readable(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"

        async def fake_get_workflow(workflow_id: str) -> dict:
            if workflow_id == MINIMAL_WORKFLOW["id"]:
                return dict(MINIMAL_WORKFLOW)
            return await workflow_config_service.get_workflow(workflow_id)

        try:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "app.services.workflow_service.workflow_config_service.get_workflow",
                side_effect=fake_get_workflow,
            ):
                project_dir = Path(tmp)
                with TestClient(app) as client:
                    session_response = client.post(
                        "/api/sessions",
                        json={"title": "Integration Project", "project_path": str(project_dir)},
                    )
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()

                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": MINIMAL_WORKFLOW["id"],
                            "requirement": "用 Python 寫一個小工具，並產生規格與 todo。",
                            "project_path": str(project_dir),
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = run_response.json()

                    run = self._wait_for_terminal_run(client, run)

                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertTrue(all(step["status"] == "passed" for step in run["steps"]))

                    artifact_names = {artifact["name"]: artifact for artifact in run["artifacts"]}
                    self.assertIn("spec.md", artifact_names)
                    self.assertIn("todo.md", artifact_names)

                    spec = client.get(f"/api/artifacts/{artifact_names['spec.md']['id']}")
                    todo = client.get(f"/api/artifacts/{artifact_names['todo.md']['id']}")
                    self.assertEqual(spec.status_code, 200, spec.text)
                    self.assertEqual(todo.status_code, 200, todo.text)
                    self.assertIn("## Acceptance Criteria", spec.json()["content"])
                    self.assertIn("## Todo List", todo.json()["content"])

                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve

    def test_system_workflow_mock_e2e_completes_all_steps(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"

        try:
            with tempfile.TemporaryDirectory() as tmp:
                project_dir = Path(tmp)
                (project_dir / "seed.py").write_text("def seed():\n    return True\n", encoding="utf-8")

                with TestClient(app) as client:
                    session_response = client.post(
                        "/api/sessions",
                        json={"title": "System Workflow E2E", "project_path": str(project_dir)},
                    )
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()

                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": "system-controlled-qwen",
                            "requirement": "新增一個 deterministic workflow greeting helper，並完整跑 system workflow mock e2e。",
                            "project_path": str(project_dir),
                            "test_command": "python -m unittest discover -s tests",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = self._wait_for_terminal_run(client, run_response.json(), timeout_sec=20)

                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertEqual(
                        [step["key"] for step in run["steps"]],
                        [
                            "prepare_project",
                            "reason_requirement",
                            "generate_spec",
                            "validate_spec",
                            "review_spec",
                            "spec_gate",
                            "generate_todo",
                            "validate_todo",
                            "review_todo",
                            "todo_gate",
                            "generate_tests",
                            "reason_build",
                            "build",
                            "run_test",
                            "final_review",
                            "final_gate",
                        ],
                    )
                    self.assertTrue(all(step["status"] == "passed" for step in run["steps"]))

                    artifact_names = {artifact["name"]: artifact for artifact in run["artifacts"]}
                    for name in [
                        "architecture.md",
                        "reasoning.md",
                        "spec.md",
                        "spec-review.md",
                        "todo.md",
                        "todo-review.md",
                        "test-plan.md",
                        "build-reasoning.md",
                        "build-result.md",
                        "test-result.md",
                        "final-review.md",
                    ]:
                        self.assertIn(name, artifact_names)

                    self.assertTrue((project_dir / "architecture.md").exists())
                    self.assertTrue((project_dir / "workflow_mock_feature.py").exists())
                    self.assertTrue((project_dir / "tests" / "test_workflow_mock_feature.py").exists())

                    test_result = client.get(f"/api/artifacts/{artifact_names['test-result.md']['id']}")
                    self.assertEqual(test_result.status_code, 200, test_result.text)
                    self.assertIn("ExitCode: 0", test_result.json()["content"])

                    final_review = client.get(f"/api/artifacts/{artifact_names['final-review.md']['id']}")
                    self.assertEqual(final_review.status_code, 200, final_review.text)
                    self.assertIn("Status: PASS", final_review.json()["content"])

                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve


if __name__ == "__main__":
    unittest.main()
