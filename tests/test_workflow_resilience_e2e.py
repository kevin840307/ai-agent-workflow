from __future__ import annotations

import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules import api as runtime
from app.testing.mock_agent import mock_qwen_response
from app.runtime_modules.files import apply_extracted_files, extract_build_files, validate_build_files_are_not_tests, validate_generated_test_files
from app.services import workflow_config_service


VALID_SPEC = """## Goal
- Validate controlled workflow behavior.

## Scope
- Exercise one backend workflow path.

## Out of Scope
- External Qwen, browser automation, and deployment.

## Input
- Requirement and project path.

## Output
- Deterministic workflow artifacts.

## Rules
- Keep generated files inside the selected project path.

## Acceptance Criteria
- AC-001: The workflow reaches the expected state.

## Unknowns
- None blocking.
"""

VALID_TODO = """## Todo List
- TODO-001: Implement AC-001.

## Test Plan
- TEST-001: Verify AC-001.

## Done Criteria
- AC-001 is implemented and verified.
"""


def _step(
    key: str,
    *,
    step_type: str = "ai",
    output: str | None = None,
    expected: list[str] | None = None,
    function: str = "",
    retry_from: str = "",
    max_retries: int = 0,
    fail_action: str = "same_step",
    timeout_minutes: float | None = None,
    template_path: str = "steps/general-auto-development/03_build.md",
    review_mode: str = "none",
) -> dict:
    prompt_markers = {
        "generate_spec": "You are generating the workflow artifact `output/spec.md`.",
        "review_spec": "You are reviewing `output/spec.md`.",
        "generate_tests": "You are generating automated tests and `test-plan.md`.",
        "build": "Build implementation and write `build-result.md`.",
    }
    return {
        "id": f"test-{key}",
        "key": key,
        "name": key.replace("_", " ").title(),
        "type": step_type,
        "enabled": True,
        "templatePath": template_path,
        "templateContent": prompt_markers.get(key, f"Workflow test step: {key}. Produce the expected artifact."),
        "filename": output or "",
        "outputFile": output or "",
        "maxRetries": max_retries,
        "failAction": fail_action,
        "retryFromStepKey": retry_from,
        "allowInteraction": False,
        "expectedFiles": expected or ([] if not output else [output]),
        "function": function,
        "reviewMode": review_mode,
        "timeoutEnabled": timeout_minutes is not None,
        "timeoutMinutes": timeout_minutes or 0,
        "injectFailureFeedback": True,
        "contextArtifacts": [],
    }


def _workflow(workflow_id: str, steps: list[dict]) -> dict:
    return {
        "id": workflow_id,
        "kind": "custom",
        "name": workflow_id,
        "folderName": "general-auto-development",
        "skillRoot": "",
        "steps": steps,
    }


@contextmanager
def mock_qwen_env():
    old_mock = os.environ.get("QWEN_MOCK")
    old_use_serve = os.environ.get("QWEN_USE_SERVE")
    old_show = os.environ.get("QWEN_WORKFLOW_SHOW_AGENT_STDOUT")
    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    try:
        yield
    finally:
        if old_mock is None:
            os.environ.pop("QWEN_MOCK", None)
        else:
            os.environ["QWEN_MOCK"] = old_mock
        if old_use_serve is None:
            os.environ.pop("QWEN_USE_SERVE", None)
        else:
            os.environ["QWEN_USE_SERVE"] = old_use_serve
        if old_show is None:
            os.environ.pop("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", None)
        else:
            os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = old_show


class WorkflowResilienceE2ETests(unittest.TestCase):
    def _wait_for_terminal_run(self, client: TestClient, run: dict, timeout_sec: float = 10) -> dict:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            latest = client.get(f"/api/workflow-runs/{run['id']}")
            self.assertEqual(latest.status_code, 200, latest.text)
            run = latest.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                cleanup_deadline = time.time() + 2
                while time.time() < cleanup_deadline:
                    task = runtime.running_tasks.get(run["id"])
                    if task is None or task.done():
                        return run
                    time.sleep(0.01)
                return run
            time.sleep(0.05)
        self.fail(f"workflow run did not reach a terminal state within {timeout_sec}s: {run}")

    def _session(self, client: TestClient, project_dir: Path, title: str = "Workflow Test") -> dict:
        response = client.post("/api/sessions", json={"title": title, "project_path": str(project_dir)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _run(
        self,
        client: TestClient,
        session: dict,
        workflow_id: str,
        project_dir: Path,
        *,
        requirement: str = "Build a workflow resilience fixture.",
        test_command: str | None = None,
    ) -> dict:
        payload = {
            "workflow_id": workflow_id,
            "requirement": requirement,
            "project_path": str(project_dir),
        }
        if test_command:
            payload["test_command"] = test_command
        response = client.post(f"/api/sessions/{session['id']}/workflow-runs", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _patched_workflow(self, workflow: dict):
        original_get_workflow = workflow_config_service.get_workflow

        async def fake_get_workflow(workflow_id: str) -> dict:
            if workflow_id == workflow["id"]:
                return workflow
            return await original_get_workflow(workflow_id)

        return patch("app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow)

    def test_reset_clears_current_session_without_creating_project(self) -> None:
        workflow = _workflow(
            "reset-contract-workflow",
            [_step("raw_artifact", output="raw.md")],
        )

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nReset contract artifact.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                before_sessions = client.get("/api/sessions").json()
                session = self._session(client, project_dir, "Reset Contract")
                original_session_id = session["id"]
                original_qwen_session_id = session["qwen_session_id"]
                client.post(f"/api/sessions/{session['id']}/messages", json={"content": "hello"})
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))
                self.assertEqual(run["status"], "done")
                self.assertTrue(run["artifacts"])

                reset = client.post(f"/api/sessions/{session['id']}/reset")
                self.assertEqual(reset.status_code, 200, reset.text)
                reset_session = reset.json()
                after_sessions = client.get("/api/sessions").json()

                self.assertEqual(reset_session["id"], original_session_id)
                self.assertNotEqual(reset_session["qwen_session_id"], original_qwen_session_id)
                self.assertEqual(len(after_sessions), len(before_sessions) + 1)
                self.assertEqual(client.get(f"/api/sessions/{session['id']}/messages").json(), [])
                self.assertIsNone(client.get(f"/api/sessions/{session['id']}/workflow-runs/latest").json())
                session_runs_dir = project_dir / ".qwen-workflow" / "runs" / f"session-{session['id']}"
                self.assertFalse(any(session_runs_dir.glob("run-*")) if session_runs_dir.exists() else False)

                client.delete(f"/api/sessions/{session['id']}")

    def test_retry_failed_step_continues_from_correct_step(self) -> None:
        workflow = _workflow(
            "retry-from-generate-spec-workflow",
            [
                _step("generate_spec", output="spec.md", expected=["spec.md"], max_retries=1),
                _step(
                    "review_spec",
                    output="spec-review.md",
                    expected=["spec-review.md"],
                    retry_from="generate_spec",
                    max_retries=1,
                    fail_action="selected_step",
                    function="",
                    template_path="steps/general-auto-development/02_implementation_review.md",
                    review_mode="current_session",
                ),
                _step("spec_gate", step_type="gate", function="require_status_pass", retry_from="generate_spec"),
                _step("after_gate", output="after.md", expected=["after.md"], template_path="steps/general-auto-development/03_build.md"),
            ],
        )
        calls = {"generate_spec": 0, "review_spec": 0, "after_gate": 0}

        def qwen_response(prompt: str) -> str:
            if "you are reviewing `output/spec.md`" in prompt.lower():
                calls["review_spec"] += 1
                if calls["review_spec"] == 1:
                    return "Status: FAIL\n\n## Findings\n- First review rejects the spec.\nConfidence: 1.0\n"
                return "Status: PASS\n\n## Findings\n- Retry fixed the issue.\nConfidence: 1.0\n"
            if "you are generating the workflow artifact `output/spec.md`" in prompt.lower():
                calls["generate_spec"] += 1
                return VALID_SPEC
            calls["after_gate"] += 1
            return "Status: DONE\n\nAfter gate artifact.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Retry Contract")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))

                self.assertEqual(run["status"], "done", run.get("error"))
                statuses = {step["key"]: step["status"] for step in run["steps"]}
                self.assertEqual(statuses, {"generate_spec": "passed", "review_spec": "passed", "spec_gate": "passed", "after_gate": "passed"})
                self.assertEqual(calls["review_spec"], 2)
                self.assertEqual(calls["generate_spec"], 2)
                # Retry accounting belongs to the step that actually failed, not the recovery target.
                self.assertEqual(next(step for step in run["steps"] if step["key"] == "generate_spec")["retry_count"], 0)
                self.assertEqual(next(step for step in run["steps"] if step["key"] == "review_spec")["retry_count"], 1)
                self.assertEqual(calls["after_gate"], 1)

                client.delete(f"/api/sessions/{session['id']}")

    def test_gate_blocks_when_required_artifact_missing(self) -> None:
        workflow = _workflow(
            "missing-artifact-gate-workflow",
            [
                _step("raw_artifact", output="raw.md", expected=["must-exist.md"], max_retries=0),
                _step("should_not_run", output="after.md", expected=["after.md"]),
            ],
        )

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nOnly raw.md is written; must-exist.md is intentionally missing.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Missing Artifact Gate")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))

                self.assertEqual(run["status"], "failed")
                self.assertIn("expected file(s) not found", run["error"])
                step_status = {step["key"]: step["status"] for step in run["steps"]}
                self.assertEqual(step_status["raw_artifact"], "failed")
                self.assertEqual(step_status["should_not_run"], "pending")

                client.delete(f"/api/sessions/{session['id']}")

    def test_projects_are_isolated_between_workflow_runs(self) -> None:
        workflow = _workflow("isolation-workflow", [_step("raw_artifact", output="raw.md")])

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nIsolation artifact.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            root = Path(tmp)
            project_a = root / "project-a"
            project_b = root / "project-b"
            project_a.mkdir()
            project_b.mkdir()
            project_a.joinpath("a.py").write_text("A = 1\n", encoding="utf-8")
            project_b.joinpath("b.py").write_text("B = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session_a = self._session(client, project_a, "Project A")
                session_b = self._session(client, project_b, "Project B")
                run_a = self._wait_for_terminal_run(client, self._run(client, session_a, workflow["id"], project_a))
                run_b = self._wait_for_terminal_run(client, self._run(client, session_b, workflow["id"], project_b))

                self.assertEqual(run_a["status"], "done")
                self.assertEqual(run_b["status"], "done")
                self.assertNotEqual(run_a["id"], run_b["id"])
                self.assertNotEqual(run_a["workspace"], run_b["workspace"])
                self.assertTrue(Path(run_a["workspace"]).is_relative_to(project_a))
                self.assertTrue(Path(run_b["workspace"]).is_relative_to(project_b))

                reset_a = client.post(f"/api/sessions/{session_a['id']}/reset")
                self.assertEqual(reset_a.status_code, 200, reset_a.text)
                latest_a = client.get(f"/api/sessions/{session_a['id']}/workflow-runs/latest").json()
                latest_b = client.get(f"/api/sessions/{session_b['id']}/workflow-runs/latest").json()
                self.assertIsNone(latest_a)
                self.assertEqual(latest_b["id"], run_b["id"])

                client.delete(f"/api/sessions/{session_a['id']}")
                client.delete(f"/api/sessions/{session_b['id']}")

    def test_qwen_invalid_tool_output_marks_step_failed(self) -> None:
        workflow = _workflow("invalid-qwen-output-workflow", [_step("raw_artifact", output="raw.md", expected=["raw.md"])])

        def qwen_response(prompt: str) -> str:
            return '{"name":"ask_user_question","arguments":{"question":"bad tool call"}}'

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Invalid Output")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))

                self.assertEqual(run["status"], "failed")
                self.assertIn("interaction disabled", run["error"])
                self.assertEqual(run["steps"][0]["status"], "failed")

                client.delete(f"/api/sessions/{session['id']}")

    def test_resume_state_survives_store_reload(self) -> None:
        workflow = _workflow("resume-state-workflow", [_step("raw_artifact", output="raw.md", expected=["raw.md"])])

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nPersistent artifact.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Resume State")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))
                self.assertEqual(run["status"], "done")

                # Simulate service restart/reload path by opening a new TestClient.
            with TestClient(app) as reloaded_client:
                latest = reloaded_client.get(f"/api/sessions/{session['id']}/workflow-runs/latest")
                self.assertEqual(latest.status_code, 200, latest.text)
                reloaded = latest.json()
                self.assertEqual(reloaded["id"], run["id"])
                self.assertEqual(reloaded["status"], "done")
                self.assertEqual(reloaded["steps"][0]["status"], "passed")
                artifact_names = {artifact["name"] for artifact in reloaded["artifacts"]}
                self.assertIn("raw.md", artifact_names)
                reloaded_client.delete(f"/api/sessions/{session['id']}")

    def test_system_workflow_artifact_integrity_is_not_only_file_existence(self) -> None:
        # Keep this focused on artifact content contracts. Full workflow execution is
        # covered by GoldenArtifactSnapshotTests; avoiding another full run prevents
        # this resilience suite from depending on subprocess timing.
        prompts = {
            "spec.md": "You are generating the workflow artifact `output/spec.md`.",
            "todo.md": "You are generating the workflow artifact `output/todo.md`.",
            "build-result.md": "You are implementing production code. OUTPUT_FILE: output/build-result.md",
            "test-plan.md": "You are generating automated tests. Output FILE/CONTENT/END_FILE blocks under tests/.",
            "test-result.md": "Command: python -c print ok\nExitCode: 0\n\nSTDOUT:\nok\n",
            "final-review.md": "You are doing the final workflow review.",
        }
        expectations = {
            "spec.md": ["## Goal", "## Acceptance Criteria", "AC-001"],
            "todo.md": ["## Todo List", "## Test Plan", "TODO-001", "TEST-001"],
            "build-result.md": ["FILE: workflow_mock_feature.py", "def workflow_greeting"],
            "test-plan.md": ["FILE: tests/test_workflow_mock_feature.py", "unittest"],
            "test-result.md": ["ExitCode: 0"],
            "final-review.md": ["Status: PASS"],
        }

        artifacts = {name: (prompt if name == "test-result.md" else mock_qwen_response(prompt)) for name, prompt in prompts.items()}
        for name, required_texts in expectations.items():
            with self.subTest(name=name):
                content = artifacts[name]
                self.assertGreater(len(content.strip()), 20)
                for required_text in required_texts:
                    self.assertIn(required_text, content)

        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            build_files = extract_build_files(artifacts["build-result.md"])
            validate_build_files_are_not_tests(build_files)
            written = apply_extracted_files(project_dir, build_files, output_label="build output")
            self.assertEqual([path.relative_to(project_dir).as_posix() for path in written], ["workflow_mock_feature.py"])
            self.assertEqual((project_dir / "workflow_mock_feature.py").read_text(encoding="utf-8").count("def workflow_greeting"), 1)

            test_files = extract_build_files(artifacts["test-plan.md"])
            validate_generated_test_files(test_files)
            apply_extracted_files(project_dir, test_files, output_label="test output")
            self.assertTrue((project_dir / "tests" / "test_workflow_mock_feature.py").exists())

    def test_project_diff_gate_fails_when_required_step_does_not_change_project(self) -> None:
        workflow = _workflow(
            "project-diff-gate-workflow",
            [
                {
                    **_step("raw_artifact", output="raw.md", expected=["raw.md"]),
                    "requireProjectChanges": True,
                }
            ],
        )

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nGenerated analysis only.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Diff Gate")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))

                self.assertEqual(run["status"], "failed")
                self.assertEqual(run.get("error_code"), "PROJECT_DIFF_MISSING")
                step = next(item for item in run["steps"] if item["key"] == "raw_artifact")
                self.assertEqual(step.get("error_code"), "PROJECT_DIFF_MISSING")

    def test_timeout_marks_step_failed_and_does_not_hang(self) -> None:
        workflow = _workflow(
            "timeout-workflow",
            [_step("slow_artifact", output="slow.md", expected=["slow.md"], timeout_minutes=0.000001)],
        )

        def qwen_response(prompt: str) -> str:
            return "\n".join(["Status: DONE", *[f"line {i}" for i in range(80)]])

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Timeout")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir), timeout_sec=5)

                self.assertEqual(run["status"], "failed")
                self.assertIn("timed out", run["error"])
                self.assertEqual(run["steps"][0]["status"], "failed")

                client.delete(f"/api/sessions/{session['id']}")

    def test_concurrent_run_for_same_project_reuses_active_run(self) -> None:
        workflow = _workflow("concurrent-workflow", [_step("raw_artifact", output="raw.md", expected=["raw.md"])])

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nConcurrent run artifact.\n"

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp)
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Concurrent")
                first = self._run(client, session, workflow["id"], project_dir)
                second = self._run(client, session, workflow["id"], project_dir)

                self.assertEqual(second["id"], first["id"])
                final = self._wait_for_terminal_run(client, first)
                self.assertEqual(final["status"], "done")

                client.delete(f"/api/sessions/{session['id']}")

    def test_build_output_path_traversal_fails_before_writing_outside_project(self) -> None:
        workflow = _workflow(
            "build-path-traversal-workflow",
            [
                _step("generate_tests", output="test-plan.md", expected=["test-plan.md"], template_path="steps/general-auto-development/03_generate_tests.md"),
                _step("build", output="build-result.md", expected=["build-result.md"], template_path="steps/general-auto-development/03_build.md"),
            ],
        )

        def qwen_response(prompt: str) -> str:
            if "generating automated tests" in prompt.lower() or "test-plan.md" in prompt:
                return """Status: DONE

FILE: tests/test_dummy.py
CONTENT:
def test_dummy():
    assert True
END_FILE
"""
            return """FILE: ../outside.py
CONTENT:
print('escaped')
END_FILE
"""

        with mock_qwen_env(), tempfile.TemporaryDirectory() as tmp, self._patched_workflow(workflow), patch(
            "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
        ):
            project_dir = Path(tmp) / "project"
            project_dir.mkdir()
            project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
            with TestClient(app) as client:
                session = self._session(client, project_dir, "Path Traversal")
                run = self._wait_for_terminal_run(client, self._run(client, session, workflow["id"], project_dir))

                self.assertEqual(run["status"], "failed")
                self.assertIn("unsafe file path", run["error"])
                self.assertFalse((Path(tmp) / "outside.py").exists())

                client.delete(f"/api/sessions/{session['id']}")

    def test_workflow_preview_source_hides_step_descriptions_after_loaded_run(self) -> None:
        source = Path("static/js/features/workflows.js").read_text(encoding="utf-8")

        self.assertIn("function hasLoadedRunForWorkflow(workflowId)", source)
        self.assertIn("state.activeRunWorkflowId === workflowId", source)
        self.assertIn("const compact = locked || hasLoadedRun", source)
        self.assertIn("const descriptionHtml = compact ? \"\"", source)
        self.assertIn("const stepsHtml = compact ? \"\"", source)
        self.assertIn("Run loaded", source)


if __name__ == "__main__":
    unittest.main()
