from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app


class ProductizationNextFeatureTests(unittest.TestCase):
    def test_advanced_label_and_model_word_removed_from_composer(self) -> None:
        html = Path("static/index.html").read_text(encoding="utf-8")
        self.assertIn(">Options<", html)
        self.assertIn("composerAdvancedSettings", html)
        self.assertIn("Model Profile", html)
        self.assertIn("技術診斷", html)
        runs_js = Path("static/js/features/runs.js").read_text(encoding="utf-8")
        self.assertIn("/console", runs_js)
        self.assertIn("/patch", runs_js)
        self.assertIn("/version-meta", runs_js)

    def test_context_pack_crud_and_productization_endpoints(self) -> None:
        with TestClient(app) as client:
            upsert = client.put(
                "/api/context-packs/regression-demo",
                json={
                    "name": "Regression Demo",
                    "description": "SOP and coding rules",
                    "files": [
                        {"path": "architecture.md", "content": "# Architecture\nUse Python runner as controller."},
                        {"path": "validation-rules.md", "content": "validation.py is the acceptance oracle."},
                    ],
                },
            )
            self.assertEqual(upsert.status_code, 200, upsert.text)
            payload = upsert.json()
            self.assertIn("prompt_context", payload)
            self.assertIn("validation.py", payload["prompt_context"])

            listed = client.get("/api/context-packs")
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertTrue(any(item["id"] == "regression-demo" for item in listed.json()["packs"]))

            for path in ["/api/workflow-benchmarks", "/api/workflows/validate", "/api/workflow-runs/active", "/api/workflow-runs/queue"]:
                resp = client.get(path)
                self.assertEqual(resp.status_code, 200, f"{path}: {resp.text}")

            matrix = client.post("/api/real-agent-matrix", json={"agents": ["qwen"], "workflows": ["adaptive-auto-workflow"], "cases": ["sort"]})
            self.assertEqual(matrix.status_code, 200, matrix.text)
            self.assertEqual(matrix.json()["count"], 1)
            self.assertIn("run_real_agent_smoke.py", matrix.json()["rows"][0]["command"])
            self.assertEqual(matrix.json()["rows"][0]["acceptance"]["external_validation"], "passed")
            self.assertIn("AgentExecutionService", matrix.json()["summary"]["shared_core"])
            cli = subprocess.run(
                [sys.executable, "scripts/run_real_agent_matrix.py", "--agent", "qwen", "--workflow", "adaptive-auto-workflow", "--case", "sort"],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(cli.returncode, 0, cli.stderr + cli.stdout)
            self.assertIn('"count": 1', cli.stdout)

    def test_dry_run_patch_console_version_and_strict_apply_gate(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        os.environ["QWEN_MOCK"] = "1"
        try:
            with TemporaryDirectory() as tmp, TestClient(app) as client:
                project = Path(tmp) / "project"
                project.mkdir()
                (project / "README.md").write_text("# Project\n", encoding="utf-8")
                (project / "validation.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
                session = client.post("/api/sessions", json={"title": "patch", "project_path": str(project)})
                self.assertEqual(session.status_code, 200, session.text)
                run_resp = client.post(
                    f"/api/sessions/{session.json()['id']}/workflow-runs",
                    json={
                        "workflow_id": "adaptive-auto-workflow",
                        "project_path": str(project),
                        "requirement": "Create sorting_algorithms.py with bubble_sort(data).",
                        "runProfile": "small",
                        "patchMode": "dry_run",
                        "workflowVersion": "test-v1",
                        "promptVersion": "prompt-v1",
                        "contractVersion": "contract-v1",
                        "runTimeoutSec": 60,
                    },
                )
                self.assertEqual(run_resp.status_code, 200, run_resp.text)
                run_id = run_resp.json()["id"]
                deadline = time.time() + 70
                current = run_resp.json()
                while time.time() < deadline:
                    current = client.get(f"/api/workflow-runs/{run_id}").json()
                    if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
                        break
                    time.sleep(0.1)
                self.assertIn(current.get("status"), {"done", "failed", "waiting_input", "cancelled"})
                self.assertEqual(current.get("patch_mode"), "dry_run")
                self.assertNotEqual(current.get("project_path"), str(project))
                self.assertEqual(current.get("original_project_path"), str(project))

                console = client.get(f"/api/workflow-runs/{run_id}/console")
                self.assertEqual(console.status_code, 200, console.text)
                self.assertEqual(console.json()["schema"], "aiwf.run-console.v1")
                self.assertIn("summary", console.json())

                version = client.get(f"/api/workflow-runs/{run_id}/version-meta")
                self.assertEqual(version.status_code, 200, version.text)
                self.assertEqual(version.json()["workflow_version"], "test-v1")
                self.assertEqual(version.json()["prompt_version"], "prompt-v1")

                patch = client.get(f"/api/workflow-runs/{run_id}/patch")
                self.assertEqual(patch.status_code, 200, patch.text)
                self.assertEqual(patch.json()["mode"], "dry_run")
                self.assertIn("changed_files", patch.json())
                if patch.json().get("changed_files"):
                    patch_payload = patch.json()
                    approve_resp = client.post(
                        f"/api/workflow-runs/{run_id}/actions",
                        json={
                            "action": "approve",
                            "files": patch_payload["changed_files"],
                            "patch_hash": patch_payload["patch_hash"],
                        },
                    )
                    self.assertEqual(approve_resp.status_code, 409, approve_resp.text)
                    self.assertEqual(approve_resp.json()["error"]["code"], "VALIDATION_NOT_PASSED")
                    self.assertFalse((project / "sorting_algorithms.py").exists(), "blocked approval must not apply the isolated Patch")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock


if __name__ == "__main__":
    unittest.main()
