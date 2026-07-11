from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.run_diff import build_run_diff, write_baseline_snapshot, write_run_diff_artifacts


class PracticalPlatformFeatureTests(unittest.TestCase):
    def test_failure_classifier_uses_canonical_classes(self) -> None:
        self.assertEqual(classify_failure("project changes were required, but no files changed")["code"], "NO_FILE_CHANGE")
        self.assertEqual(classify_failure("validation.py failed with AssertionError")["code"], "VALIDATION_FAILED")
        self.assertEqual(classify_failure("pytest failed: assert 1 == 2")["code"], "TEST_FAILED")
        self.assertEqual(classify_failure("unsafe file path outside project")["code"], "PROJECT_GUARD_BLOCKED")
        self.assertEqual(classify_failure("qwen returned tool-call JSON write_file")["code"], "INVALID_OUTPUT")

    def test_run_diff_snapshot_detects_project_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            run_dir = Path(tmp) / "run"
            project.mkdir()
            (run_dir / ".workflow").mkdir(parents=True)
            (project / "README.md").write_text("# A\n", encoding="utf-8")
            run = {"id": "run-1", "project_path": str(project), "workspace": str(run_dir)}
            write_baseline_snapshot(run, run_dir)
            (project / "README.md").write_text("# A\n\n## Usage\n", encoding="utf-8")
            (project / "helper.py").write_text("def ok():\n    return True\n", encoding="utf-8")
            diff = write_run_diff_artifacts(run, run_dir)
            self.assertEqual(diff["file_count"], 2)
            self.assertTrue((run_dir / ".workflow" / "run-diff.md").exists())
            self.assertIn("helper.py", (run_dir / ".workflow" / "run-diff.md").read_text(encoding="utf-8"))
            rebuilt = build_run_diff(run, run_dir)
            self.assertEqual(rebuilt["file_count"], 2)

    def test_validation_script_generator_api_writes_and_runs(self) -> None:
        with TemporaryDirectory() as tmp, TestClient(app) as client:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "sorting_algorithms.py").write_text(
                "def bubble_sort(data):\n    return sorted(data)\n",
                encoding="utf-8",
            )
            resp = client.post(
                "/api/validation-scripts/generate",
                json={
                    "requirement": "Create sorting_algorithms.py with bubble_sort",
                    "expectedResult": "bubble_sort should return a sorted list",
                    "projectPath": str(project),
                    "write": True,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertIn("bubble_sort", body["script"])
            self.assertTrue((project / "validation.py").exists())
            run = subprocess.run([sys.executable, "validation.py"], cwd=project, text=True, capture_output=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)

    def test_case_library_api_and_real_agent_smoke_list_cases(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TestClient(app) as client:
            resp = client.get("/api/workflow-cases")
            self.assertEqual(resp.status_code, 200, resp.text)
            cases = resp.json()["cases"]
            self.assertGreaterEqual(len(cases), 8)
            first = client.get(f"/api/workflow-cases/{cases[0]['id']}")
            self.assertEqual(first.status_code, 200, first.text)
            self.assertIn("requirement", first.json())
        listed = subprocess.run(
            [sys.executable, "scripts/run_real_agent_smoke.py", "--list-cases"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr + listed.stdout)
        self.assertIn("sort", listed.stdout)

    def test_rerun_diff_and_failure_api_endpoints_are_available(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        old_norm = os.environ.get("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
        try:
            with TemporaryDirectory() as tmp, TestClient(app) as client:
                project = Path(tmp) / "project"
                project.mkdir()
                (project / "README.md").write_text("# Project\n", encoding="utf-8")
                session = client.post("/api/sessions", json={"title": "features", "project_path": str(project)}).json()
                run = client.post(
                    f"/api/sessions/{session['id']}/workflow-runs",
                    json={
                        "workflow_id": "adaptive-auto-workflow",
                        "project_path": str(project),
                        "requirement": "Create sort_utils.py with bubble_sort(data).",
                        "runProfile": "small",
                    },
                ).json()
                deadline = time.time() + 60
                current = run
                while time.time() < deadline:
                    current = client.get(f"/api/workflow-runs/{run['id']}").json()
                    if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
                        break
                    time.sleep(0.1)
                self.assertIn(current.get("status"), {"done", "failed", "waiting_input", "cancelled"})
                diff = client.get(f"/api/workflow-runs/{run['id']}/diff")
                self.assertEqual(diff.status_code, 200, diff.text)
                self.assertIn("files", diff.json())
                failures = client.get(f"/api/workflow-runs/{run['id']}/failures")
                self.assertEqual(failures.status_code, 200, failures.text)
                rerun = client.post(f"/api/workflow-runs/{run['id']}/steps/rerun", json={"step_key": "generate_task_prompts", "mode": "from_step"})
                self.assertLess(rerun.status_code, 500, rerun.text)
                client.post(f"/api/workflow-runs/{run['id']}/terminate")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_norm is None:
                os.environ.pop("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION", None)
            else:
                os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = old_norm

    def test_debug_tools_ui_replaces_old_advanced_badge(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index = (root / "static/index.html").read_text(encoding="utf-8")
        css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
        runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
        self.assertIn("Options", index)
        self.assertIn("技術診斷", index)
        self.assertNotIn("Advanced controller view", css)
        self.assertIn("openRunDiff", runs)
        self.assertIn("openRunConsole", runs)
        self.assertIn("openPatchPreview", runs)
        self.assertIn("openVersionMeta", runs)
        self.assertIn("changesPanel", runs)
        self.assertIn("/diff", runs)


if __name__ == "__main__":
    unittest.main()
