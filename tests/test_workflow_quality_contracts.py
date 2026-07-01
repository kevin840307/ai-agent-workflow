from __future__ import annotations

import os
import json
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules import api as runtime
from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import apply_extracted_files
from app.workflow_runtime.step_utils import expected_file_candidates
from app.services import workflow_config_service


def _step(
    key: str,
    *,
    step_type: str = "ai",
    output: str | None = None,
    expected: list[str] | None = None,
    function: str = "",
    template_path: str = "prompts/01_spec.md",
) -> dict:
    return {
        "id": f"quality-{key}",
        "key": key,
        "name": key.replace("_", " ").title(),
        "type": step_type,
        "enabled": True,
        "templatePath": template_path,
        "filename": output or "",
        "outputFile": output or "",
        "maxRetries": 0,
        "failAction": "same_step",
        "retryFromStepKey": "",
        "allowInteraction": False,
        "expectedFiles": expected if expected is not None else ([] if not output else [output]),
        "function": function,
        "reviewMode": "none",
        "timeoutEnabled": False,
        "timeoutMinutes": 0,
        "injectFailureFeedback": True,
        "contextArtifacts": [],
    }


def _workflow(workflow_id: str, steps: list[dict]) -> dict:
    return {
        "id": workflow_id,
        "kind": "custom",
        "name": workflow_id,
        "description": "Quality contract test workflow.",
        "folderName": "system-controlled-qwen",
        "skillRoot": "",
        "steps": steps,
    }


@contextmanager
def _mock_qwen_env():
    old = {name: os.environ.get(name) for name in ["QWEN_MOCK", "QWEN_USE_SERVE", "QWEN_WORKFLOW_SHOW_AGENT_STDOUT"]}
    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    try:
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class _WorkflowTestSupport:
    def _wait_for_terminal_run(self, client: TestClient, run: dict, timeout_sec: float = 10) -> dict:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            response = client.get(f"/api/workflow-runs/{run['id']}")
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                # The store is updated just before the asyncio task done-callback
                # removes runtime.running_tasks.  Wait for that cleanup so later
                # tests do not inherit an apparently active run.
                cleanup_deadline = time.time() + 2
                while time.time() < cleanup_deadline:
                    task = runtime.running_tasks.get(run["id"])
                    if task is None or task.done():
                        return run
                    time.sleep(0.01)
                return run
            time.sleep(0.05)
        self.fail(f"workflow did not finish within {timeout_sec}s: {run}")

    def _session(self, client: TestClient, project_dir: Path, title: str = "Quality Contract") -> dict:
        response = client.post("/api/sessions", json={"title": title, "project_path": str(project_dir)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _patched_workflow(self, workflow: dict):
        original_get_workflow = workflow_config_service.get_workflow

        async def fake_get_workflow(workflow_id: str) -> dict:
            if workflow_id == workflow["id"]:
                return workflow
            return await original_get_workflow(workflow_id)

        return patch("app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow)

    def _start_run(self, client: TestClient, session: dict, workflow: dict, project_dir: Path, requirement: str = "quality contract") -> dict:
        response = client.post(
            f"/api/sessions/{session['id']}/workflow-runs",
            json={"workflow_id": workflow["id"], "project_path": str(project_dir), "requirement": requirement},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class ApiResponseSnapshotContractTests(_WorkflowTestSupport, unittest.TestCase):
    def test_workflow_api_response_shapes_stay_frontend_compatible(self) -> None:
        workflow = _workflow("api-response-snapshot-workflow", [_step("raw_artifact", output="raw.md")])

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nAPI response snapshot artifact.\n"

        with _mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("README.md").write_text("# API Snapshot\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "API Snapshot")
                run = self._wait_for_terminal_run(client, self._start_run(client, session, workflow, project_dir))

                latest = client.get(f"/api/sessions/{session['id']}/workflow-runs/latest")
                self.assertEqual(latest.status_code, 200, latest.text)
                latest_run = latest.json()
                self.assertEqual(latest_run["id"], run["id"])

                required_run_keys = {
                    "id",
                    "session_id",
                    "qwen_session_id",
                    "status",
                    "error",
                    "workspace",
                    "project_path",
                    "workflow_id",
                    "workflow_name",
                    "test_command",
                    "steps",
                    "artifacts",
                    "created_at",
                    "updated_at",
                    "started_at",
                    "ended_at",
                }
                self.assertTrue(required_run_keys.issubset(latest_run.keys()), sorted(set(required_run_keys) - set(latest_run.keys())))
                self.assertEqual(latest_run["status"], "done")
                self.assertIsInstance(latest_run["steps"], list)
                self.assertIsInstance(latest_run["artifacts"], list)

                step = latest_run["steps"][0]
                for key in ["key", "title", "status", "error", "started_at", "ended_at", "retry_count", "config"]:
                    self.assertIn(key, step)
                self.assertEqual(step["key"], "raw_artifact")
                self.assertEqual(step["status"], "passed")

                artifacts = client.get(f"/api/workflow-runs/{run['id']}/artifacts")
                self.assertEqual(artifacts.status_code, 200, artifacts.text)
                artifact_list = artifacts.json()
                self.assertTrue(artifact_list)
                for artifact in artifact_list:
                    with self.subTest(path=artifact.get("path")):
                        for key in ["id", "name", "path", "size", "updated_at"]:
                            self.assertIn(key, artifact)

                raw_artifact = next(item for item in artifact_list if item["path"] == "output/raw.md")
                content = client.get(f"/api/artifacts/{raw_artifact['id']}")
                self.assertEqual(content.status_code, 200, content.text)
                artifact_payload = content.json()
                self.assertEqual(set(artifact_payload), {"id", "name", "path", "content"})
                self.assertIn("API response snapshot artifact", artifact_payload["content"])

                retry = client.post(f"/api/workflow-runs/{run['id']}/retry", json={"step_key": "raw_artifact"})
                self.assertEqual(retry.status_code, 200, retry.text)
                retry_payload = retry.json()
                self.assertTrue(required_run_keys.issubset(retry_payload.keys()))
                retried_run = self._wait_for_terminal_run(client, retry_payload)
                self.assertIn(retried_run["status"], {"done", "failed"})

                reset = client.post(f"/api/sessions/{session['id']}/reset")
                self.assertEqual(reset.status_code, 200, reset.text)
                reset_payload = reset.json()
                for key in ["id", "title", "project_path", "qwen_session_id", "created_at", "updated_at"]:
                    self.assertIn(key, reset_payload)
                self.assertEqual(reset_payload["id"], session["id"])

                client.delete(f"/api/sessions/{session['id']}")


class ObservabilityAndPerformanceTests(_WorkflowTestSupport, unittest.TestCase):
    def test_run_log_contains_ids_step_status_and_terminal_event(self) -> None:
        workflow = _workflow("observability-workflow", [_step("raw_artifact", output="raw.md")])

        with _mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow):
            project_dir = Path(tmp)
            project_dir.joinpath("README.md").write_text("# Observability\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Observability")
                run = self._wait_for_terminal_run(client, self._start_run(client, session, workflow, project_dir))
                self.assertEqual(run["status"], "done", run.get("error"))
                log_artifact = next(item for item in run["artifacts"] if item["path"] == ".workflow/run-log.md")
                log_payload = client.get(f"/api/artifacts/{log_artifact['id']}").json()
                log_text = log_payload["content"]

                self.assertIn(f"run_id={run['id']}", log_text)
                self.assertIn(f"session_id={session['id']}", log_text)
                self.assertIn("workflow: started", log_text)
                self.assertIn("raw_artifact: started", log_text)
                self.assertIn("raw_artifact: passed", log_text)
                self.assertIn("workflow: done", log_text)

                summary_artifact = next(item for item in run["artifacts"] if item["path"] == ".workflow/run-summary.md")
                summary_payload = client.get(f"/api/artifacts/{summary_artifact['id']}").json()
                self.assertIn("# Run Summary", summary_payload["content"])
                self.assertIn("Status: DONE", summary_payload["content"])
                self.assertIn("Raw Artifact", summary_payload["content"])

                trace_artifact = next(item for item in run["artifacts"] if item["path"] == ".workflow/run-trace.json")
                trace_payload = client.get(f"/api/artifacts/{trace_artifact['id']}").json()
                trace = json.loads(trace_payload["content"])
                self.assertEqual(trace["run_id"], run["id"])
                self.assertEqual(trace["status"], "done")
                self.assertEqual(trace["step_count"], 1)
                self.assertEqual(trace["steps"][0]["key"], "raw_artifact")
                self.assertGreater(trace["steps"][0]["prompt_chars"], 0)
                client.delete(f"/api/sessions/{session['id']}")

    def test_core_api_performance_baseline_uses_generous_thresholds(self) -> None:
        workflow = _workflow("performance-baseline-workflow", [_step("raw_artifact", output="raw.md")])
        thresholds = {
            "create_session": 5.0,
            "create_run_to_terminal": 10.0,
            "get_latest_run": 3.0,
            "list_artifacts": 3.0,
            "reset_session": 5.0,
        }

        timings: dict[str, float] = {}
        with _mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow):
            project_dir = Path(tmp)
            project_dir.joinpath("README.md").write_text("# Perf\n", encoding="utf-8")
            with TestClient(app) as client:
                start = time.perf_counter()
                session = self._session(client, project_dir, "Performance")
                timings["create_session"] = time.perf_counter() - start

                start = time.perf_counter()
                run = self._wait_for_terminal_run(client, self._start_run(client, session, workflow, project_dir))
                timings["create_run_to_terminal"] = time.perf_counter() - start
                self.assertEqual(run["status"], "done")

                start = time.perf_counter()
                latest = client.get(f"/api/sessions/{session['id']}/workflow-runs/latest")
                self.assertEqual(latest.status_code, 200, latest.text)
                timings["get_latest_run"] = time.perf_counter() - start

                start = time.perf_counter()
                artifacts = client.get(f"/api/workflow-runs/{run['id']}/artifacts")
                self.assertEqual(artifacts.status_code, 200, artifacts.text)
                timings["list_artifacts"] = time.perf_counter() - start

                start = time.perf_counter()
                reset = client.post(f"/api/sessions/{session['id']}/reset")
                self.assertEqual(reset.status_code, 200, reset.text)
                timings["reset_session"] = time.perf_counter() - start

                client.delete(f"/api/sessions/{session['id']}")

        for name, threshold in thresholds.items():
            with self.subTest(name=name):
                self.assertLess(timings[name], threshold, f"{name} took {timings[name]:.3f}s; baseline threshold is {threshold:.3f}s")


class FileOutputFuzzSecurityTests(unittest.TestCase):
    def test_agent_file_output_rejects_fuzzed_escape_paths(self) -> None:
        unsafe_paths = [
            "../evil.py",
            "..\\evil.py",
            "/tmp/evil.py",
            "C:\\temp\\evil.py",
            "C:/temp/evil.py",
            "\\\\server\\share\\evil.py",
            "//server/share/evil.py",
            "output/%2e%2e/evil.py",
            "output/.. /evil.py",
            ".qwen-workflow/state.json",
            "src/%2e%2e/%2e%2e/evil.py",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            for rel_path in unsafe_paths:
                with self.subTest(rel_path=rel_path):
                    with self.assertRaises(WorkflowError):
                        apply_extracted_files(project_dir, [(rel_path, "x = 1\n")], output_label="fuzz output")

    def test_expected_file_candidates_rejects_fuzzed_escape_paths(self) -> None:
        unsafe_paths = [
            "../evil.md",
            "..\\evil.md",
            "/tmp/evil.md",
            "C:\\temp\\evil.md",
            "C:/temp/evil.md",
            "\\\\server\\share\\evil.md",
            "//server/share/evil.md",
            "output/%2e%2e/evil.md",
            "output/.. /evil.md",
            ".qwen-workflow/state.json",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            project = Path(tmp) / "project"
            project.mkdir()
            run = {"workspace": str(workspace), "project_path": str(project)}
            for rel_path in unsafe_paths:
                with self.subTest(rel_path=rel_path):
                    with self.assertRaises(WorkflowError):
                        expected_file_candidates(run, rel_path)

    def test_safe_nested_output_paths_are_still_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            written = apply_extracted_files(project_dir, [("src/features/good.py", "VALUE = 1\n")])
            self.assertEqual(len(written), 1)
            self.assertTrue((project_dir / "src" / "features" / "good.py").exists())

            workspace = project_dir / ".qwen-workflow" / "runs" / "r1"
            workspace.mkdir(parents=True)
            run = {"workspace": str(workspace), "project_path": str(project_dir)}
            candidates = expected_file_candidates(run, "output/spec.md")
            self.assertTrue(any(candidate.parts[-2:] == ("output", "spec.md") for candidate in candidates))


if __name__ == "__main__":
    unittest.main()
