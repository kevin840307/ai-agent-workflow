from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import app
from app.persistence.json_store import Store
from app.runtime_modules import api as runtime
from app.workflow_runtime.run_lifecycle import (
    cleanup_stale_project_lock,
    mark_cancel_requested,
    project_lock_path,
    read_project_lock,
    recover_stale_active_runs_for_project,
    write_project_lock,
)
from scripts import run_tests


class TestPipelineContractTests(unittest.TestCase):
    def test_grouped_test_runner_covers_every_test_module(self) -> None:
        report = run_tests.coverage_report()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["extra"], [])
        self.assertEqual(report["duplicates"], [])
        self.assertGreaterEqual(report["discovered_count"], 1)

    def test_test_runner_has_separate_fast_and_e2e_modes(self) -> None:
        fast = {name for name, _files in run_tests.selected_groups("fast")}
        e2e = {name for name, _files in run_tests.selected_groups("e2e")}
        self.assertTrue(fast)
        self.assertTrue(e2e)
        self.assertTrue(fast.isdisjoint(e2e))


class RunLifecycleContractTests(unittest.TestCase):

    def test_lifecycle_api_route_is_registered(self) -> None:
        routes = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/workflow-runs/{run_id}/lifecycle", routes)

    def test_project_run_lock_is_written_and_stale_lock_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            run = {
                "id": "run-lock",
                "session_id": "session-lock",
                "workflow_id": "wf",
                "status": "queued",
                "project_path": str(project_dir),
                "original_project_path": str(project_dir),
                "created_at": "t0",
            }
            lock = write_project_lock(run)
            self.assertEqual(lock["run_id"], "run-lock")
            self.assertTrue(project_lock_path(project_dir).exists())
            self.assertEqual(read_project_lock(project_dir)["run_id"], "run-lock")

            cleanup = cleanup_stale_project_lock(project_dir, {"runs": [{**run, "status": "failed"}]})
            self.assertTrue(cleanup["removed"], cleanup)
            self.assertFalse(project_lock_path(project_dir).exists())

    def test_cancel_request_marks_run_cancelling_with_reason(self) -> None:
        run = {"id": "run-cancel", "status": "running"}
        mark_cancel_requested(run, reason="stop now")
        self.assertEqual(run["status"], "cancelling")
        self.assertTrue(run["cancel_requested"])
        self.assertEqual(run["cancel_reason"], "stop now")
        self.assertIn("cancel_requested_at", run)


    def test_dead_owner_active_run_is_recovered_instead_of_blocking_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            run = {
                "id": "dead-owner-run",
                "session_id": "s",
                "status": "running",
                "workspace": str(project_dir / ".qwen-workflow" / "runs" / "session-s" / "run-dead-owner-run"),
                "project_path": str(project_dir),
                "original_project_path": str(project_dir),
                "run_owner": {"host": "localhost", "pid": 99999999, "id": "localhost:99999999"},
                "steps": [{"key": "build", "status": "running", "error": None}],
            }
            data = {"runs": [run]}
            with patch("app.workflow_runtime.run_lifecycle.owner_process_is_alive", return_value=False):
                recovered = recover_stale_active_runs_for_project(data, project_dir)
            self.assertEqual([item["id"] for item in recovered], ["dead-owner-run"])
            self.assertEqual(data["runs"][0]["status"], "failed")
            self.assertEqual(data["runs"][0]["error_code"], "INTERRUPTED")
            self.assertTrue(data["runs"][0]["restart_recoverable"])
            self.assertEqual(data["runs"][0]["steps"][0]["status"], "failed")

    def test_restart_recovery_writes_state_file_log_and_clears_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            run_dir = project_dir / ".qwen-workflow" / "runs" / "session-s" / "run-r"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / ".workflow" / "run-log.md").write_text("", encoding="utf-8")
            store = Store(Path(tmp) / "store.json", default_project_path=lambda: str(project_dir), default_steps=lambda: [])
            run = {
                "id": "r",
                "session_id": "s",
                "status": "running",
                "workspace": str(run_dir),
                "project_path": str(project_dir),
                "original_project_path": str(project_dir),
                "steps": [{"key": "build", "status": "running", "error": None}],
            }
            store.save_sync({"sessions": [], "messages": [], "workflow_configs": [], "runs": [run]})
            write_project_lock(run)
            self.assertTrue(project_lock_path(project_dir).exists())

            with patch("app.runtime_modules.api.store", store):
                runtime.mark_interrupted_runs()

            recovered = store.load_sync()["runs"][0]
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["error_code"], "INTERRUPTED")
            self.assertTrue(recovered["restart_recoverable"])
            state = json.loads((run_dir / ".workflow" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "failed")
            self.assertIn("interrupted by server restart", (run_dir / ".workflow" / "run-log.md").read_text(encoding="utf-8"))
            self.assertFalse(project_lock_path(project_dir).exists())


if __name__ == "__main__":
    unittest.main()
