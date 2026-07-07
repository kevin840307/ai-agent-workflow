from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.persistence.json_store import Store
from app.services import maintenance_service
from app.stores import FileArtifactStore, FileLockStore, FileRunStore, FileStepStore
from app.workflow_runtime.run_lifecycle import (
    ACTIVE_RUN_STATUSES,
    cleanup_stale_project_lock,
    find_active_run_for_project,
    mark_cancel_requested,
    project_lock_path,
    recover_stale_active_runs_for_project,
    write_project_lock,
)
from scripts import run_browser_ui_smoke, run_tests


class StoreAbstractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmp.name) / "project"
        self.project_dir.mkdir()
        self.store = Store(Path(self.tmp.name) / "store.json", default_project_path=lambda: str(self.project_dir), default_steps=lambda: [])
        self.store.save_sync(
            {
                "sessions": [],
                "messages": [],
                "workflow_configs": [],
                "runs": [
                    {
                        "id": "r1",
                        "session_id": "s1",
                        "status": "done",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "project_path": str(self.project_dir),
                        "steps": [{"key": "build", "status": "passed"}],
                        "artifacts": [{"id": "r1:a", "path": "output/a.md"}],
                    },
                    {
                        "id": "r2",
                        "session_id": "s1",
                        "status": "queued",
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "project_path": str(self.project_dir),
                        "steps": [{"key": "plan", "status": "pending"}],
                        "artifacts": [],
                    },
                ],
            }
        )
        self.run_store = FileRunStore(read=self.store.read, mutate=self.store.mutate)
        self.step_store = FileStepStore(self.run_store)
        self.artifact_store = FileArtifactStore(self.run_store)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_file_backed_stores_read_runs_steps_and_artifacts(self) -> None:
        self.assertEqual((await self.run_store.get("r1"))["id"], "r1")
        self.assertEqual((await self.run_store.latest_for_session("s1"))["id"], "r2")
        self.assertEqual([run["id"] for run in await self.run_store.list_active(ACTIVE_RUN_STATUSES)], ["r2"])
        self.assertEqual((await self.step_store.get("r1", "build"))["status"], "passed")
        self.assertEqual((await self.artifact_store.list_for_run("r1"))[0]["path"], "output/a.md")

    async def test_file_lock_store_wraps_project_lock_lifecycle(self) -> None:
        lock_store = FileLockStore()
        run = {"id": "r-lock", "session_id": "s", "status": "queued", "project_path": str(self.project_dir), "original_project_path": str(self.project_dir)}
        lock = lock_store.write_project_lock(run)
        self.assertEqual(lock["run_id"], "r-lock")
        self.assertTrue(project_lock_path(self.project_dir).exists())
        result = lock_store.cleanup_stale_project_lock(self.project_dir, {"runs": [{**run, "status": "failed"}]})
        self.assertTrue(result["removed"], result)


class ArtifactRetentionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tmp.name) / "project"
        self.project_dir.mkdir()
        self.store = Store(Path(self.tmp.name) / "store.json", default_project_path=lambda: str(self.project_dir), default_steps=lambda: [])
        runs = []
        for idx in range(4):
            run_dir = self.project_dir / ".qwen-workflow" / "runs" / "session-s" / f"run-r{idx}"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / ".workflow" / "state.json").write_text("{}", encoding="utf-8")
            runs.append(
                {
                    "id": f"r{idx}",
                    "session_id": "s",
                    "status": "done",
                    "project_path": str(self.project_dir),
                    "original_project_path": str(self.project_dir),
                    "workspace": str(run_dir),
                    "created_at": f"2026-01-0{idx+1}T00:00:00+00:00",
                    "updated_at": f"2026-01-0{idx+1}T00:00:00+00:00",
                }
            )
        self.orphan = self.project_dir / ".qwen-workflow" / "runs" / "session-s" / "run-orphan"
        (self.orphan / ".workflow").mkdir(parents=True)
        self.store.save_sync({"sessions": [], "messages": [], "workflow_configs": [], "runs": runs})

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_cleanup_supports_dry_run_retention_and_orphan_cleanup(self) -> None:
        with patch("app.persistence.repositories.store.read", self.store.read), patch("app.persistence.repositories.store.mutate", self.store.mutate):
            preview = await maintenance_service.cleanup_runs(keep_per_project=2, dry_run=True, include_orphan_workspaces=True)
            self.assertTrue(preview["dryRun"])
            self.assertEqual(preview["removedRuns"], 2)
            self.assertEqual(preview["orphanWorkspaceCount"], 1)
            self.assertTrue(self.orphan.exists())
            result = await maintenance_service.cleanup_runs(keep_per_project=2, dry_run=False, include_orphan_workspaces=True)
        self.assertEqual(result["removedRuns"], 2)
        self.assertFalse(self.orphan.exists())
        remaining = {run["id"] for run in self.store.load_sync()["runs"]}
        self.assertEqual(remaining, {"r2", "r3"})


class BrowserUiSmokeTests(unittest.TestCase):
    def test_static_browser_ui_smoke_contract(self) -> None:
        result = run_browser_ui_smoke.static_smoke()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema"], "aiwf.browser-ui-smoke.v1")

    def test_browser_smoke_can_be_run_from_test_matrix(self) -> None:
        report = run_tests.coverage_report()
        self.assertTrue(report["ok"], report)
        self.assertIn("tests/test_hardening_next.py", run_tests.grouped_test_files())


class LifecycleStressTests(unittest.TestCase):
    def test_same_project_active_run_guard_prefers_live_run_and_recovers_dead_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            live = {"id": "live", "status": "running", "project_path": str(project_dir), "original_project_path": str(project_dir), "run_owner": {"pid": 1}}
            dead = {
                "id": "dead",
                "status": "running",
                "project_path": str(project_dir),
                "original_project_path": str(project_dir),
                "run_owner": {"host": "localhost", "pid": 99999999, "id": "localhost:99999999"},
                "steps": [{"key": "build", "status": "running"}],
            }
            data = {"runs": [dead]}
            with patch("app.workflow_runtime.run_lifecycle.owner_process_is_alive", return_value=False):
                recovered = recover_stale_active_runs_for_project(data, project_dir)
            self.assertEqual(recovered[0]["id"], "dead")
            self.assertEqual(data["runs"][0]["status"], "failed")

            data = {"runs": [live]}
            with patch("app.workflow_runtime.run_lifecycle.owner_process_is_alive", return_value=True):
                active = find_active_run_for_project(data, project_dir)
            self.assertEqual(active["id"], "live")

    def test_cancel_and_lock_cleanup_are_idempotent_under_repeated_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            run = {"id": "r", "session_id": "s", "status": "running", "project_path": str(project_dir), "original_project_path": str(project_dir)}
            write_project_lock(run)
            mark_cancel_requested(run, reason="stress cancel")
            mark_cancel_requested(run, reason="stress cancel")
            self.assertEqual(run["status"], "cancelling")
            self.assertTrue(project_lock_path(project_dir).exists())
            self.assertTrue(cleanup_stale_project_lock(project_dir, {"runs": [{**run, "status": "failed"}]} )["removed"])
            self.assertFalse(project_lock_path(project_dir).exists())
            self.assertFalse(cleanup_stale_project_lock(project_dir, {"runs": []})["removed"])

    def test_maintenance_route_exposes_retention_options(self) -> None:
        routes = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/maintenance/cleanup", routes)
