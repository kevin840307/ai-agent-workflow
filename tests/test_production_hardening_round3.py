from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.persistence.sqlite_store import SQLiteStore
from app.runtime_modules.run_state import RunState
from app.runtime_modules.events import EventBus
from app.services import workflow_service
from app.stores import FileArtifactStore, FileRunStore, FileStepStore


class StoreBackendAndStateConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_run_state_uses_store_abstractions_for_steps_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            run_dir = project / ".qwen-workflow" / "runs" / "session-s" / "run-r"
            (run_dir / ".workflow").mkdir(parents=True)
            store = SQLiteStore(Path(tmp) / "aiwf.sqlite3", default_project_path=lambda: str(project), default_steps=lambda: [])
            store.save_sync(
                {
                    "sessions": [],
                    "messages": [],
                    "workflow_configs": [],
                    "runs": [
                        {
                            "id": "r",
                            "session_id": "s",
                            "status": "queued",
                            "workspace": str(run_dir),
                            "project_path": str(project),
                            "steps": [{"key": "build", "status": "pending"}],
                            "artifacts": [],
                            "timeline": [],
                        }
                    ],
                }
            )
            state = RunState(store, EventBus())
            await state.set_step("r", "build", "running")
            await state.set_step("r", "build", "passed")
            (run_dir / "output").mkdir(parents=True)
            (run_dir / "output" / "build-result.md").write_text("Status: READY\n", encoding="utf-8")
            await state.refresh_artifacts("r")
            run = await state.get_run_record("r")
            step = run["steps"][0]
            assert step["status"] == "passed"
            assert step["started_at"]
            assert step["ended_at"]
            assert any(item["path"] == "output/build-result.md" for item in run["artifacts"])

    async def test_sqlite_store_backend_roundtrip_and_transactional_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "state.sqlite3", default_project_path=lambda: tmp, default_steps=lambda: [])
            await store.mutate(lambda data: data["runs"].append({"id": "r1", "session_id": "s", "status": "queued", "steps": []}))
            await store.mutate(lambda data: data["runs"][0].update({"status": "done"}))
            data = await store.read()
            assert data["runs"][0]["status"] == "done"
            assert (Path(tmp) / "state.sqlite3").exists()

    async def test_file_store_interfaces_support_artifact_replace(self) -> None:
        data = {"runs": [{"id": "r", "session_id": "s", "status": "queued", "steps": [], "artifacts": []}]}

        async def read():
            return data

        async def mutate(fn):
            return fn(data)

        run_store = FileRunStore(read=read, mutate=mutate)
        artifact_store = FileArtifactStore(run_store)
        await artifact_store.replace_for_run("r", [{"id": "a", "path": "output/a.md"}])
        assert (await artifact_store.list_for_run("r"))[0]["path"] == "output/a.md"


class ProductionGateAndDebugBundleTests(unittest.TestCase):
    def test_production_acceptance_quick_passes_and_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "scripts/run_production_acceptance.py", "--quick", "--output", tmp],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=240,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = Path(tmp) / "production-acceptance-report.json"
            self.assertTrue(report.exists())
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], "aiwf.production-acceptance.v1")
            self.assertEqual(data["status"], "PASS")

    def test_debug_bundle_api_summarizes_run_for_copy_paste(self) -> None:
        run = {
            "id": "debug-run",
            "session_id": "s",
            "workflow_id": "general-auto-development",
            "workflow_name": "General Auto Development",
            "status": "failed",
            "error": "boom",
            "error_code": "TEST_FAILED",
            "patch_mode": "review",
            "patch_status": "pending",
            "project_path": "/tmp/isolated",
            "original_project_path": "/tmp/project",
            "workspace": "/tmp/workspace",
            "steps": [
                {"key": "build", "status": "passed", "retry_count": 1},
                {"key": "run_test", "status": "failed", "error_code": "TEST_FAILED", "error": "pytest failed", "retry_count": 2},
            ],
            "artifacts": [{"id": "a", "path": "output/test-result.md"}],
        }
        with patch("app.services.workflow_service.get_run", new=lambda run_id: asyncio.sleep(0, result=run)):
            bundle = asyncio.run(workflow_service.get_run_debug_bundle("debug-run"))
        self.assertEqual(bundle["schema"], "aiwf.debug-bundle.v1")
        self.assertEqual(bundle["failedStep"], "run_test")
        self.assertEqual(bundle["failureType"], "TEST_FAILED")
        self.assertEqual(bundle["retryCount"], 3)

    def test_debug_bundle_route_and_ui_contract_exist(self) -> None:
        routes = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/workflow-runs/{run_id}/debug-bundle", routes)
        diagnostics_js = Path("static/js/features/diagnostics.js").read_text(encoding="utf-8")
        index = Path("static/index.html").read_text(encoding="utf-8")
        self.assertIn("downloadDebugBundle", diagnostics_js)
        self.assertIn("debug-bundle", diagnostics_js)
        self.assertIn("匯出技術診斷", index)


class ActionsSplitAndLimitationsTests(unittest.TestCase):
    def test_actions_py_is_significantly_split_into_mixins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        actions_source = (root / "app/workflow_runtime/actions.py").read_text(encoding="utf-8")
        task_mixin = root / "app/workflow_runtime/task_loop_actions.py"
        review_mixin = root / "app/workflow_runtime/review_actions.py"
        self.assertTrue(task_mixin.exists())
        self.assertTrue(review_mixin.exists())
        self.assertIn("TaskLoopActionsMixin", actions_source)
        self.assertIn("ReviewActionsMixin", actions_source)
        self.assertLess(len(actions_source.splitlines()), 1700)

    def test_known_limitations_document_is_explicit(self) -> None:
        doc = Path("doc/KNOWN_LIMITATIONS.md").read_text(encoding="utf-8")
        self.assertIn("Small/local models may plan correctly but fail to create or modify files", doc)
        self.assertIn("patchMode=review", doc)
        self.assertIn("scripts/run_production_acceptance.py", doc)

    def test_run_tests_matrix_includes_round3_tests(self) -> None:
        from scripts import run_tests

        self.assertIn("tests/test_production_hardening_round3.py", run_tests.grouped_test_files())
        self.assertTrue(run_tests.coverage_report()["ok"])


if __name__ == "__main__":
    unittest.main()
