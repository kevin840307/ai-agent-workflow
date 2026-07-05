from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.runtime_modules import api as runtime
from app.domain.schemas import CreateRunRequest
from app.main import app
from app.runtime_modules.qwen import QwenCliClient
from app.persistence.json_store import Store
from app.services import workflow_config_service, workflow_service


SYSTEM_ARTIFACT_SECTIONS = {
    "spec.md": ["## Goal", "## Scope", "## Acceptance Criteria"],
    "todo.md": ["## Todo List", "## Test Plan", "## Done Criteria"],
    "spec-review.md": ["Status: PASS"],
    "todo-review.md": ["Status: PASS"],
    "final-review.md": ["Status: PASS"],
    "test-result.md": ["ExitCode: 0"],
    "build-result.md": ["# Build Direct Edit Result", "`workflow_mock_feature.py`"],
    "test-plan.md": ["# Generated Tests Direct Edit Result", "`tests/test_workflow_mock_feature.py`"],
}


MINIMAL_WORKFLOW = {
    "id": "advanced-stability-minimal",
    "kind": "custom",
    "name": "Advanced Stability Minimal",
    "folderName": "system-controlled-qwen",
    "skillRoot": "",
    "steps": [
        {
            "id": "advanced-step",
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
            "function": "",
        }
    ],
}


def restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


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
            restore_env(key, value)


async def noop(*args, **kwargs):
    return None


class RealQwenSmokeTests(unittest.TestCase):
    def test_real_qwen_cli_smoke_is_opt_in(self) -> None:
        if os.environ.get("RUN_REAL_QWEN") != "1":
            self.skipTest("Set RUN_REAL_QWEN=1 to smoke test the installed real Qwen CLI.")
        qwen_bin = os.environ.get("QWEN_BIN") or ("qwen.cmd" if os.name == "nt" else "qwen")
        if shutil.which(qwen_bin) is None:
            self.skipTest(f"Qwen CLI not found: {qwen_bin}")

        with tempfile.TemporaryDirectory() as tmp, Env(QWEN_MOCK="0", QWEN_USE_SERVE="0", QWEN_TIMEOUT_SEC=os.environ.get("QWEN_TIMEOUT_SEC", "60")):
            client = QwenCliClient({"reuse_session": False})
            output = client.run(
                "Reply with one short line containing QWEN_SMOKE_OK. Do not create files.",
                Path(tmp),
                timeout_sec=int(os.environ.get("QWEN_TIMEOUT_SEC", "60")),
            )
            self.assertTrue(output.strip(), "real Qwen CLI should return non-empty stdout")


class GoldenArtifactSnapshotTests(unittest.TestCase):
    def _wait_for_terminal_run(self, client: TestClient, run_id: str, timeout_sec: float = 60) -> dict:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            response = client.get(f"/api/workflow-runs/{run_id}")
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                return run
            time.sleep(0.05)
        self.fail(f"workflow run did not finish within {timeout_sec} seconds")

    def test_system_workflow_golden_artifact_structure_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, Env(QWEN_MOCK="1", QWEN_USE_SERVE="0", QWEN_WORKFLOW_SHOW_AGENT_STDOUT="0"):
            project_dir = Path(tmp)
            (project_dir / "README.md").write_text("# Golden Snapshot\n", encoding="utf-8")
            with TestClient(app) as client:
                session_response = client.post("/api/sessions", json={"title": "Golden Snapshot", "project_path": str(project_dir)})
                self.assertEqual(session_response.status_code, 200, session_response.text)
                session = session_response.json()
                run_response = client.post(
                    f"/api/sessions/{session['id']}/workflow-runs",
                    json={
                        "workflow_id": workflow_config_service.SYSTEM_WORKFLOW_ID,
                        "project_path": str(project_dir),
                        "requirement": "新增一個 deterministic Python helper，並用 unittest 驗證。",
                        "test_command": "python -m unittest discover -s tests",
                    },
                )
                self.assertEqual(run_response.status_code, 200, run_response.text)
                run = self._wait_for_terminal_run(client, run_response.json()["id"])
                self.assertEqual(run["status"], "done", run.get("error"))

                output_dir = Path(run["workspace"]) / "output"
                for filename, required_markers in SYSTEM_ARTIFACT_SECTIONS.items():
                    with self.subTest(filename=filename):
                        content = (output_dir / filename).read_text(encoding="utf-8")
                        self.assertGreater(len(content.strip()), 20)
                        for marker in required_markers:
                            self.assertIn(marker, content)

                self.assertTrue((project_dir / "workflow_mock_feature.py").exists())
                self.assertTrue((project_dir / "tests" / "test_workflow_mock_feature.py").exists())
                client.delete(f"/api/sessions/{session['id']}")


class StoreMigrationAndCrashRecoveryTests(unittest.TestCase):
    def _store(self, store_path: Path, project_path: Path, default_steps=None) -> Store:
        return Store(store_path, default_project_path=lambda: str(project_path), default_steps=lambda: default_steps or [])

    def test_workflow_store_migration_loads_old_fixture_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            run_dir = project_dir / ".qwen-workflow" / "runs" / "session-old" / "run-old"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / "output").mkdir(parents=True)
            old_fixture = {
                "sessions": [{"id": "old-session", "title": "Old", "project_path": str(project_dir)}],
                "messages": [],
                "runs": [
                    {
                        "id": "old-run",
                        "session_id": "old-session",
                        "workspace": str(run_dir),
                        "project_path": str(project_dir),
                        "steps": [{"key": "legacy_step"}],
                    }
                ],
            }
            store_path = Path(tmp) / "workflow_store.json"
            store_path.write_text(json.dumps(old_fixture), encoding="utf-8")

            loaded = self._store(store_path, project_dir).load_sync()
            session = loaded["sessions"][0]
            run = loaded["runs"][0]

            self.assertEqual(session["qwen_session_id"], "old-session")
            self.assertEqual(run["qwen_session_id"], "old-session")
            self.assertEqual(run["status"], "queued")
            self.assertIsNone(run["error"])
            self.assertEqual(run["artifacts"], [])
            self.assertIn("workflow_id", run)
            self.assertEqual(run["steps"][0]["status"], "pending")
            self.assertEqual(run["steps"][0]["retry_count"], 0)

    def test_crash_recovery_marks_stale_running_runs_failed_and_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            run_dir = project_dir / ".qwen-workflow" / "runs" / "session-crash" / "run-crash"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / "output").mkdir(parents=True)
            store_path = Path(tmp) / "store.json"
            store = self._store(store_path, project_dir)
            store.save_sync(
                {
                    "sessions": [{"id": "session-crash", "project_path": str(project_dir), "qwen_session_id": "qwen-crash"}],
                    "messages": [],
                    "workflow_configs": [],
                    "runs": [
                        {
                            "id": "run-crash",
                            "session_id": "session-crash",
                            "qwen_session_id": "qwen-crash",
                            "status": "running",
                            "error": None,
                            "workspace": str(run_dir),
                            "project_path": str(project_dir),
                            "steps": [
                                {"key": "spec", "status": "passed", "started_at": "t1", "ended_at": "t2", "error": None, "retry_count": 0},
                                {"key": "build", "status": "running", "started_at": "t3", "ended_at": None, "error": None, "retry_count": 0},
                                {"key": "run_test", "status": "pending", "started_at": None, "ended_at": None, "error": None, "retry_count": 0},
                            ],
                        }
                    ],
                }
            )

            with patch("app.runtime_modules.api.store", store):
                runtime.mark_interrupted_runs()

            recovered = store.load_sync()["runs"][0]
            self.assertEqual(recovered["status"], "failed")
            self.assertIn("server restarted", recovered["error"])
            self.assertEqual(recovered["steps"][0]["status"], "passed")
            self.assertEqual(recovered["steps"][1]["status"], "failed")
            self.assertIn("server restarted", recovered["steps"][1]["error"])
            self.assertEqual(recovered["steps"][2]["status"], "pending")

            # A recovered failed run must not block a future run for the same project.
            active = [run for run in store.load_sync()["runs"] if run.get("status") in workflow_service.ACTIVE_RUN_STATUSES]
            self.assertEqual(active, [])

    def test_crash_recovery_does_not_interrupt_live_owner_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            run_dir = project_dir / ".qwen-workflow" / "runs" / "session-live" / "run-live"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / "output").mkdir(parents=True)
            store_path = Path(tmp) / "store.json"
            store = self._store(store_path, project_dir)
            live_owner = {"id": "other-runtime", "host": "test-host", "pid": 12345, "started_at": "t0"}
            store.save_sync(
                {
                    "sessions": [{"id": "session-live", "project_path": str(project_dir), "qwen_session_id": "qwen-live"}],
                    "messages": [],
                    "workflow_configs": [],
                    "runs": [
                        {
                            "id": "run-live",
                            "session_id": "session-live",
                            "qwen_session_id": "qwen-live",
                            "run_owner": live_owner,
                            "status": "running",
                            "error": None,
                            "workspace": str(run_dir),
                            "project_path": str(project_dir),
                            "steps": [{"key": "build", "status": "running", "error": None, "retry_count": 0}],
                        }
                    ],
                }
            )

            with (
                patch("app.runtime_modules.api.store", store),
                patch("app.runtime_modules.api.owner_matches_current_process", return_value=False),
                patch("app.runtime_modules.api.owner_process_is_alive", return_value=True),
            ):
                runtime.mark_interrupted_runs()

            recovered = store.load_sync()["runs"][0]
            self.assertEqual(recovered["status"], "running")
            self.assertIsNone(recovered["error"])
            self.assertEqual(recovered["steps"][0]["status"], "running")


class WorkflowRunRehydrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_answers_rehydrates_missing_store_run_from_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            run_id = "run-rehydrate"
            session_id = "session-rehydrate"
            run_dir = project_dir / ".qwen-workflow" / "runs" / f"session-{session_id}" / f"run-{run_id}"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / "input").mkdir()
            (run_dir / "output").mkdir()
            (run_dir / "input" / "questions.md").write_text("## Question\n\nWhich language should be used?", encoding="utf-8")
            (run_dir / ".workflow" / "run-log.md").write_text("", encoding="utf-8")
            state = {
                "id": run_id,
                "session_id": session_id,
                "qwen_session_id": session_id,
                "agent_session_ids": {"qwen": session_id, "opencode": session_id},
                "status": "waiting_input",
                "error": "prepare_project: qwen needs more user input. See input/questions.md.",
                "workspace": str(run_dir),
                "project_path": str(project_dir),
                "workflow_id": workflow_config_service.SYSTEM_WORKFLOW_ID,
                "workflow_folder": "system-controlled-qwen",
                "workflow_name": "System Controlled Qwen",
                "skill_root": "",
                "test_command": None,
                "steps": [
                    {
                        "key": "prepare_project",
                        "name": "Prepare Project",
                        "status": "waiting_input",
                        "started_at": None,
                        "ended_at": None,
                        "error": "prepare_project: qwen needs more user input. See input/questions.md.",
                        "retry_count": 0,
                        "events": [],
                    },
                    {
                        "key": "generate_spec",
                        "name": "Generate Spec",
                        "status": "pending",
                        "started_at": None,
                        "ended_at": None,
                        "error": None,
                        "retry_count": 0,
                        "events": [],
                    },
                ],
                "artifacts": [],
                "timeline": [],
                "created_at": runtime.utc_now(),
                "updated_at": runtime.utc_now(),
                "started_at": None,
                "ended_at": runtime.utc_now(),
            }
            (run_dir / ".workflow" / "state.json").write_text(json.dumps(state), encoding="utf-8")
            store = Store(Path(tmp) / "store.json", default_project_path=lambda: str(project_dir), default_steps=lambda: [])
            store.save_sync(
                {
                    "sessions": [
                        {
                            "id": session_id,
                            "title": "Recover",
                            "project_path": str(project_dir),
                            "qwen_session_id": session_id,
                            "agent_session_ids": {"qwen": session_id, "opencode": session_id},
                        }
                    ],
                    "messages": [],
                    "runs": [],
                    "workflow_configs": [],
                }
            )

            with patch("app.runtime_modules.api.store", store), patch("app.runtime_modules.api.run_state.store", store), patch(
                "app.services.workflow_service.start_workflow_task"
            ):
                run = await workflow_service.submit_answers(run_id, runtime.SubmitAnswersRequest(content="Use Python."))

            self.assertEqual(run["id"], run_id)
            self.assertEqual(run["status"], "queued")
            self.assertTrue((run_dir / "input" / "answers.md").read_text(encoding="utf-8").strip())
            self.assertEqual(store.load_sync()["runs"][0]["id"], run_id)
            self.assertEqual(store.load_sync()["messages"][0]["kind"], "answer")


class WorkflowRunRaceConditionTests(unittest.IsolatedAsyncioTestCase):
    def _temp_runtime_store(self, tmp: str) -> Store:
        project_dir = Path(tmp) / "project"
        project_dir.mkdir()
        store = Store(Path(tmp) / "store.json", default_project_path=lambda: str(project_dir), default_steps=lambda: [])
        store.save_sync({"sessions": [], "messages": [], "runs": [], "workflow_configs": []})
        return store

    async def _patched_workflow(self, workflow_id: str) -> dict:
        workflow = dict(MINIMAL_WORKFLOW)
        workflow["id"] = workflow_id
        return workflow

    async def test_same_project_parallel_run_requests_return_one_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            store = Store(Path(tmp) / "store.json", default_project_path=lambda: str(project_dir), default_steps=lambda: [])
            store.save_sync(
                {
                    "sessions": [{"id": "s1", "qwen_session_id": "s1", "title": "Race", "project_path": str(project_dir)}],
                    "messages": [],
                    "runs": [],
                    "workflow_configs": [],
                }
            )
            workflow = dict(MINIMAL_WORKFLOW)
            workflow["id"] = "race-same-project"

            async def fake_get_workflow(workflow_id: str) -> dict:
                await asyncio.sleep(0.001)
                return workflow

            async def fake_refresh(run_id: str):
                await asyncio.sleep(0)

            with patch("app.runtime_modules.api.store", store), patch("app.runtime_modules.api.refresh_artifacts", side_effect=fake_refresh), patch(
                "app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow
            ), patch("app.services.workflow_service.start_workflow_task"):
                body = CreateRunRequest(workflow_id=workflow["id"], requirement="race", project_path=str(project_dir))
                results = await asyncio.gather(*(workflow_service.create_workflow_run("s1", body) for _ in range(20)))

            run_ids = {run["id"] for run in results}
            stored_runs = store.load_sync()["runs"]
            self.assertEqual(len(run_ids), 1)
            self.assertEqual(len(stored_runs), 1)
            self.assertEqual(stored_runs[0]["status"], "queued")

    async def test_different_projects_parallel_run_requests_do_not_block_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = []
            for index in range(20):
                project_dir = root / f"project-{index}"
                project_dir.mkdir()
                sessions.append({"id": f"s{index}", "qwen_session_id": f"s{index}", "title": f"Race {index}", "project_path": str(project_dir)})
            store = Store(root / "store.json", default_project_path=lambda: str(root), default_steps=lambda: [])
            store.save_sync({"sessions": sessions, "messages": [], "runs": [], "workflow_configs": []})
            workflow = dict(MINIMAL_WORKFLOW)
            workflow["id"] = "race-different-projects"

            async def fake_get_workflow(workflow_id: str) -> dict:
                await asyncio.sleep(0.001)
                return workflow

            with patch("app.runtime_modules.api.store", store), patch("app.runtime_modules.api.refresh_artifacts", side_effect=noop), patch(
                "app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow
            ), patch("app.services.workflow_service.start_workflow_task"):
                results = await asyncio.gather(
                    *(
                        workflow_service.create_workflow_run(
                            session["id"],
                            CreateRunRequest(workflow_id=workflow["id"], requirement="race", project_path=session["project_path"]),
                        )
                        for session in sessions
                    )
                )

            self.assertEqual(len({run["id"] for run in results}), 20)
            self.assertEqual(len(store.load_sync()["runs"]), 20)


if __name__ == "__main__":
    unittest.main()
