from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.runtime_modules.files import project_file_snapshot, project_overview, project_profile
from app.workflow_runtime.prompt_builder import PromptBuilder
from app.services import workflow_config_service


class Env:
    def __init__(self, **updates: str) -> None:
        self.updates = updates
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        self.old = {key: os.environ.get(key) for key in self.updates}
        os.environ.update(self.updates)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def create_large_python_project(root: Path, file_count: int = 240) -> None:
    (root / "src" / "legacy").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "README.md").write_text("# Large Fixture\n", encoding="utf-8")
    (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    for index in range(file_count):
        package = root / "src" / "legacy" / f"module_{index // 20:02d}"
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / f"feature_{index:03d}.py").write_text(
            f"def feature_{index:03d}(value):\n    return value + {index}\n",
            encoding="utf-8",
        )
    for index in range(16):
        (root / "tests" / f"test_feature_{index:03d}.py").write_text(
            "import unittest\n\n\nclass LegacyFeatureTests(unittest.TestCase):\n"
            "    def test_placeholder(self):\n        self.assertTrue(True)\n",
            encoding="utf-8",
        )


def wait_for_terminal_run(client: TestClient, run_id: str, timeout_sec: float = 30) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        response = client.get(f"/api/workflow-runs/{run_id}")
        if response.status_code == 200:
            run = response.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                return run
        time.sleep(0.05)
    raise AssertionError(f"workflow run did not finish within {timeout_sec} seconds")


class LargeProjectFixtureTests(unittest.TestCase):
    def test_large_project_profile_is_bounded_and_detects_existing_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            create_large_python_project(project_dir)

            snapshot = project_file_snapshot(project_dir)
            overview = project_overview(project_dir)
            profile = project_profile(project_dir)

            self.assertGreaterEqual(len(snapshot), 250)
            self.assertIn("more files", overview)
            self.assertLess(len(overview), 12000)
            self.assertIn("Primary language: Python", profile)
            self.assertIn("pytest", profile)
            self.assertIn("src/legacy", profile)

    def test_large_project_prompt_context_stays_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            create_large_python_project(project_dir)
            run_dir = project_dir / ".qwen-workflow" / "runs" / "session-large" / "run-large"
            (run_dir / "output").mkdir(parents=True)
            (run_dir / "input").mkdir(parents=True)
            (run_dir / "prompts").mkdir(parents=True)
            (run_dir / "requirement.md").write_text("Add one deterministic helper without scanning every file.", encoding="utf-8")
            run = {
                "id": "run-large",
                "workspace": str(run_dir),
                "project_path": str(project_dir),
                "workflow_id": workflow_config_service.SYSTEM_WORKFLOW_ID,
                "workflow_folder": workflow_config_service.SYSTEM_WORKFLOW_ID,
                "skill_root": "",
                "steps": [
                    {
                        "key": "generate_spec",
                        "config": {"templatePath": "prompts/01_spec.md", "expectedFiles": ["spec.md"]},
                        "allow_interaction": False,
                    }
                ],
            }

            result = PromptBuilder().build(run, "generate_spec", "01_spec.md", allow_interaction=False)
            self.assertIn("Primary language: Python", result.prompt)
            self.assertLess(len(result.prompt), 160000)
            self.assertTrue((run_dir / "prompts" / "generate_spec.md").exists())

    def test_large_project_mock_workflow_completes_without_full_system_cost(self) -> None:
        workflow = {
            "id": "large-project-minimal",
            "kind": "custom",
            "name": "Large Project Minimal",
            "folderName": "system-controlled-qwen",
            "skillRoot": "",
            "steps": [
                {
                    "id": "large-raw",
                    "key": "raw_artifact",
                    "name": "Raw Artifact",
                    "type": "ai",
                    "enabled": True,
                    "templatePath": "prompts/01_spec.md",
                    "filename": "raw.md",
                    "outputFile": "raw.md",
                    "expectedFiles": ["raw.md"],
                    "maxRetries": 0,
                    "failAction": "same_step",
                    "retryFromStepKey": "",
                    "reviewMode": "none",
                    "allowInteraction": False,
                    "validator": "",
                    "contextArtifacts": [],
                }
            ],
        }

        async def fake_get_workflow(workflow_id: str) -> dict:
            if workflow_id == workflow["id"]:
                return workflow
            return await workflow_config_service.get_workflow(workflow_id)

        def qwen_response(prompt: str) -> str:
            self.assertIn("Project Path", prompt)
            return "Status: DONE\n\nLarge project minimal artifact.\n"

        with tempfile.TemporaryDirectory() as tmp, Env(QWEN_MOCK="1", QWEN_USE_SERVE="0", QWEN_WORKFLOW_SHOW_AGENT_STDOUT="0"), patch(
            "app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow
        ), patch("app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response):
            project_dir = Path(tmp) / "large-project"
            project_dir.mkdir()
            create_large_python_project(project_dir, file_count=80)
            with TestClient(app) as client:
                session_response = client.post("/api/sessions", json={"title": "Large", "project_path": str(project_dir)})
                self.assertEqual(session_response.status_code, 200, session_response.text)
                session = session_response.json()
                try:
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": workflow["id"],
                            "project_path": str(project_dir),
                            "requirement": "Add a tiny deterministic helper without changing unrelated legacy files.",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = wait_for_terminal_run(client, run_response.json()["id"], timeout_sec=10)
                    self.assertEqual(run["status"], "done", run.get("error"))
                    artifact_names = {artifact["name"] for artifact in run["artifacts"]}
                    self.assertIn("raw.md", artifact_names)
                finally:
                    client.delete(f"/api/sessions/{session['id']}")


if __name__ == "__main__":
    unittest.main()
