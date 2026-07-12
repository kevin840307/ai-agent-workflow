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

from app.agents.process_supervisor import ProcessSupervisorOptions, run_supervised_process, terminate_popen_tree
from app.main import app
from app.workflow_runtime.artifact_repair import repair_run_artifacts
from app.workflow_runtime.retry_guard import should_stop_retry
from app.workflow_runtime.run_artifacts import read_run_artifact_index
from app.workflow_runtime.run_consistency import check_store_consistency
from app.workflow_runtime.run_lifecycle import mark_interrupted_store_runs
from app.runtime_modules.run_owner import current_run_owner


class ReliabilityRunConsistencyAndRepairTests(unittest.TestCase):
    def _run(self, tmp: str, *, status: str = "done") -> dict:
        project = Path(tmp) / "project"
        workspace = project / ".ai-workflow" / "runs" / "session-s" / "run-r"
        (workspace / ".workflow").mkdir(parents=True, exist_ok=True)
        run = {
            "id": "r",
            "session_id": "s",
            "workflow_id": "general-auto-development",
            "status": status,
            "workspace": str(workspace),
            "project_path": str(project),
            "ended_at": "now" if status in {"done", "failed", "cancelled"} else None,
            "steps": [{"key": "build", "status": "passed", "retry_count": 0}],
            "artifacts": [],
            "timeline": [],
        }
        (workspace / ".workflow" / "state.json").write_text(json.dumps(run), encoding="utf-8")
        (workspace / ".workflow" / "events.jsonl").write_text(json.dumps({"type": "run.completed", "run_id": "r"}) + "\n", encoding="utf-8")
        return run

    def test_consistency_checker_passes_after_artifact_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp)
            repair = repair_run_artifacts(run)
            self.assertIn("artifact-index", repair["repaired"])
            report = check_store_consistency({"runs": [run]})
            self.assertEqual(report["status"], "PASS", report)
            self.assertEqual(report["error_count"], 0)
            self.assertTrue(read_run_artifact_index(run)["records"])

    def test_consistency_checker_detects_status_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(tmp, status="done")
            state_path = Path(run["workspace"]) / ".workflow" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["status"] = "running"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            report = check_store_consistency({"runs": [run]})
            self.assertEqual(report["status"], "FAIL")
            issues = report["runs"][0]["issues"]
            self.assertTrue(any(item["issue"] == "state_status_mismatch" for item in issues))

    def test_artifact_repair_api_route_exists(self) -> None:
        # FastAPI may keep included routers lazy; OpenAPI is the stable public
        # route contract regardless of the internal router representation.
        routes = set(app.openapi().get("paths", {}))
        self.assertIn("/api/workflow-runs/{run_id}/repair-artifacts", routes)
        self.assertIn("/api/workflow-runs/{run_id}/consistency", routes)


class ReliabilityRetryAndCrashRecoveryTests(unittest.TestCase):
    def test_retry_guard_stops_repeated_no_file_change(self) -> None:
        run = {}
        stop1, reason1, attempt1 = should_stop_retry(run, step_key="build", error="project changes were required, but no files changed")
        stop2, reason2, attempt2 = should_stop_retry(run, step_key="build", error="project changes were required, but no files changed")
        self.assertFalse(stop1)
        self.assertTrue(stop2)
        self.assertIn("NO_FILE_CHANGE", reason2 or "")
        self.assertEqual(attempt2["no_file_change_count"], 2)

    def test_restart_recovery_marks_waiting_input_runs_interrupted(self) -> None:
        data = {
            "runs": [
                {
                    "id": "r",
                    "status": "waiting_input",
                    "run_owner": current_run_owner(),
                    "steps": [{"key": "ask", "status": "running"}],
                }
            ]
        }
        changed = mark_interrupted_store_runs(data)
        self.assertEqual(len(changed), 1)
        self.assertEqual(data["runs"][0]["status"], "failed")
        self.assertEqual(data["runs"][0]["error_code"], "INTERRUPTED")

    def test_crash_recovery_script_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/run_crash_recovery_test.py"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('"status": "PASS"', proc.stdout)


class ReliabilityProcessAndHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_supervisor_timeout_terminates_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                await run_supervised_process(
                    ProcessSupervisorOptions(
                        command=[sys.executable, "-c", "import time; time.sleep(30)"],
                        cwd=Path(tmp),
                        timeout_sec=1,
                    )
                )

    async def test_deep_health_route_returns_checks(self) -> None:
        client = TestClient(app)
        response = client.get("/api/health/deep")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema"], "aiwf.local-health.v1")
        self.assertIn("storeReadable", payload["checks"])
        self.assertIn("workflowAssets", payload["checks"])


class ReliabilityTestTierAndUiContractTests(unittest.TestCase):
    def test_run_tests_supports_tiers_and_covers_this_file(self) -> None:
        from scripts import run_tests

        self.assertIn("unit", run_tests.TEST_TIERS)
        self.assertIn("contract", run_tests.TEST_TIERS)
        self.assertIn("tests/test_reliability_hardening_round5.py", run_tests.grouped_test_files())
        self.assertTrue(run_tests.coverage_report()["ok"])

    def test_static_ui_has_empty_state_and_workflow_console_fallbacks(self) -> None:
        dom = Path("static/js/core/dom.js").read_text(encoding="utf-8")
        runs = Path("static/js/features/runs.js").read_text(encoding="utf-8")
        styles = Path("static/styles.css").read_text(encoding="utf-8")
        self.assertIn("emptyState", dom)
        self.assertIn("safeText", dom)
        self.assertIn("No run selected", runs)
        self.assertIn("ui-empty-state", styles)

    def test_consistency_and_artifact_repair_scripts_exist(self) -> None:
        for rel in [
            "scripts/check_run_consistency.py",
            "scripts/repair_artifacts.py",
            "scripts/run_crash_recovery_test.py",
        ]:
            self.assertTrue(Path(rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
