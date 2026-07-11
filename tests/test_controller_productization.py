from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.workflow_runtime.failure_diagnosis import diagnose_agent_failure
from app.workflow_runtime.run_profiles import apply_run_profile, normalize_run_profile


class ControllerProductizationTests(unittest.TestCase):
    def test_model_capability_profiles_are_normalized_and_applied(self) -> None:
        self.assertEqual(normalize_run_profile("fast"), "small")
        self.assertEqual(normalize_run_profile("deep"), "deep")
        self.assertEqual(normalize_run_profile("normal"), "normal")
        steps = [{"key": "auto_generation", "type": "ai", "maxRetries": 99, "config": {"retryPolicy": {"maxRetries": 99}}}]
        small = apply_run_profile(steps, "small")
        self.assertEqual(small[0]["thinkingLevel"], "none")
        self.assertLessEqual(small[0]["config"]["retryPolicy"]["maxRetries"], 6)
        strong = apply_run_profile([{"key": "auto_generation", "type": "ai", "maxRetries": 1, "config": {}}], "strong")
        self.assertEqual(strong[0]["thinkingLevel"], "high")
        self.assertGreaterEqual(strong[0]["maxRetries"], 12)

    def test_agent_failure_diagnosis_classifies_common_failures(self) -> None:
        self.assertEqual(diagnose_agent_failure("build did not directly create or modify project files")["code"], "NO_PROJECT_CHANGES")
        self.assertEqual(diagnose_agent_failure("qwen returned tool-call JSON edit_file")["code"], "TOOL_CALL_JSON")
        self.assertEqual(diagnose_agent_failure("validation.py failed with AssertionError")["code"], "VALIDATION_FAILED")

    def test_real_agent_smoke_self_prompt_and_case_library_dry_run(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as tmp:
            self_prompt = subprocess.run(
                [sys.executable, "scripts/run_real_agent_smoke.py", "--self-prompt-test", "--output", str(Path(tmp) / "self"), "--case", "sort"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(self_prompt.returncode, 0, self_prompt.stderr + self_prompt.stdout)
            self.assertIn('"status": "PASS"', self_prompt.stdout)
            case_dry = subprocess.run(
                [sys.executable, "scripts/run_workflow_case_library.py", "--dry-run", "--output", str(Path(tmp) / "cases")],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(case_dry.returncode, 0, case_dry.stderr + case_dry.stdout)
            self.assertIn('"case_count": 8', case_dry.stdout)

    def test_export_and_replay_endpoints(self) -> None:
        previous_mock = os.environ.get("QWEN_MOCK")
        previous_norm = os.environ.get("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
        try:
            with TemporaryDirectory() as tmp, TestClient(app) as client:
                project = Path(tmp) / "project"
                project.mkdir()
                (project / "README.md").write_text("# Project\n", encoding="utf-8")
                session = client.post("/api/sessions", json={"title": "export", "project_path": str(project)}).json()
                run = client.post(
                    f"/api/sessions/{session['id']}/workflow-runs",
                    json={
                        "workflow_id": "adaptive-auto-workflow",
                        "project_path": str(project),
                        "requirement": "Create a tiny helper.",
                        "runProfile": "small",
                    },
                ).json()
                # It is sufficient for API availability to terminate this smoke run before export.
                client.post(f"/api/workflow-runs/{run['id']}/terminate")
                exported = client.get(f"/api/workflow-runs/{run['id']}/export")
                self.assertLess(exported.status_code, 400, exported.text[:200])
                zip_path = Path(tmp) / "bundle.zip"
                zip_path.write_bytes(exported.content)
                with zipfile.ZipFile(zip_path) as zf:
                    self.assertIn("bundle-manifest.json", zf.namelist())
                    manifest = json.loads(zf.read("bundle-manifest.json").decode("utf-8"))
                    self.assertEqual(manifest["workflow_id"], "adaptive-auto-workflow")
                replay = client.post(f"/api/workflow-runs/{run['id']}/replay", json={})
                self.assertLess(replay.status_code, 400, replay.text[:200])
                self.assertNotEqual(replay.json()["id"], run["id"])
        finally:
            if previous_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = previous_mock
            if previous_norm is None:
                os.environ.pop("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION", None)
            else:
                os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = previous_norm

    def test_ui_contains_novice_advanced_and_profile_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index = (root / "static/index.html").read_text(encoding="utf-8")
        runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
        css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
        self.assertIn("runProfile", index)
        self.assertIn("advancedMode", index)
        self.assertIn("async exportRun", runs)
        self.assertIn("匯出 Run", index)
        self.assertIn("Replay Run", runs)
        self.assertIn("novice-mode", css)

    def test_product_docs_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in [
            "QUICKSTART.md",
            "WORKFLOW_DESIGN.md",
            "RETRY_POLICY.md",
            "VALIDATION_SCRIPT.md",
            "REAL_AGENT_SMOKE.md",
            "RUN_REPLAY_EXPORT.md",
            "AGENT_FAILURE_DIAGNOSIS.md",
        ]:
            with self.subTest(name=name):
                self.assertTrue((root / "doc" / name).exists())


if __name__ == "__main__":
    unittest.main()
