from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules.errors import ValidationError, WorkflowError
from app.runtime_modules.files import (
    apply_extracted_files,
    extract_build_files,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.runtime_modules.run_state import RunState
from app.persistence.json_store import Store
from app.runtime_modules.qwen import QwenCliClient
from app.services import workflow_config_service
from app.workflow_runtime.agent_step_runner import AgentStepRunner
from app.workflow_runtime.functions import WorkflowFunctionService
from app.workflow_runtime.prompt_builder import PromptBuilder
from app.workflow_runtime.step_config import initial_steps
from app.workflow_runtime.step_utils import expected_file_candidates, expected_files


SYSTEM_STEP_ORDER = [
    "prepare_project",
    "reason_requirement",
    "generate_spec",
    "validate_spec",
    "review_spec",
    "spec_gate",
    "generate_todo",
    "validate_todo",
    "review_todo",
    "todo_gate",
    "generate_tests",
    "reason_build",
    "build",
    "run_test",
    "final_review",
    "final_gate",
]


VALID_SPEC = """## Goal
- Complete the workflow contract.

## Scope
- Implement the requested behavior.

## Out of Scope
- Unrelated refactors.

## Input
- Requirement.

## Output
- Code and tests.

## Rules
- Keep tests separate from production code.

## Acceptance Criteria
- AC-001: Behavior is implemented.

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


class DummyBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append((run_id, event))


async def _noop_log(run: dict, message: str) -> None:
    return None


async def _noop_refresh(run_id: str) -> None:
    return None


class WorkflowDefinitionIntegrityTests(unittest.TestCase):
    def _workflow_files(self) -> list[Path]:
        return sorted(Path("data/ai-workflow/workflows").glob("*.workflow"))

    def test_general_generate_tests_allows_file_block_fallback(self) -> None:
        prompt = Path("data/ai-workflow/steps/general-auto-development/03_generate_tests.md").read_text(encoding="utf-8")
        self.assertIn("FILE/CONTENT/END_FILE", prompt)
        self.assertIn("FILE: tests/test_name.py", prompt)
        self.assertNotIn("Do not output full file contents", prompt)

    def test_general_build_prompt_forbids_standalone_code_fences(self) -> None:
        prompt = Path("data/ai-workflow/steps/general-auto-development/03_build.md").read_text(encoding="utf-8")
        self.assertIn("Do not output standalone code fences", prompt)
        self.assertIn("Do not include extra code fences", prompt)

    def test_adaptive_generation_prompt_has_complete_file_block_contract(self) -> None:
        prompt = Path("data/ai-workflow/steps/adaptive-auto-workflow/00_auto_generation.md").read_text(encoding="utf-8")
        self.assertIn("FILE: relative/path/to/file.py", prompt)
        self.assertIn("CONTENT:\ncomplete file content\nEND_FILE", prompt)
        self.assertIn("tests/test_*.py", prompt)
        self.assertIn("Never put `CONTENT`", prompt)
        self.assertIn("Do not output standalone code fences", prompt)

    def test_workflow_definition_integrity(self) -> None:
        self.assertTrue(self._workflow_files(), "expected workflow assets under data/ai-workflow/workflows")
        allowed_first_segments = {"output", "input", "prompts", ".workflow"}

        for path in self._workflow_files():
            workflow = workflow_config_service.read_workflow_file(path)
            self.assertIsNotNone(workflow, f"workflow asset should load: {path}")
            folder = Path("data/ai-workflow")
            steps = [step for step in workflow.get("steps", []) if step.get("enabled") is not False]
            keys = [step.get("key") for step in steps]

            with self.subTest(workflow=workflow.get("id")):
                self.assertEqual(len(keys), len(set(keys)), "step keys must be unique")
                self.assertTrue(keys, "workflow must contain at least one enabled step")

                for step in steps:
                    key = step.get("key")
                    retry_from = str(step.get("retryFromStepKey") or step.get("failActionStepKey") or "").strip()
                    if retry_from:
                        self.assertIn(retry_from, keys, f"{key}.retryFromStepKey must point to an existing step")
                    template_path = str(step.get("templatePath") or "").replace("\\", "/")
                    if template_path:
                        self.assertFalse(Path(template_path).is_absolute(), f"{key}.templatePath must be relative")
                        self.assertNotIn("..", Path(template_path).parts, f"{key}.templatePath cannot traverse")
                        if step.get("type") in {"ai", "review", "agent"} or step.get("key") in {
                            "prepare_project",
                            "generate_spec",
                            "review_spec",
                            "generate_todo",
                            "review_todo",
                            "generate_tests",
                            "reason_requirement",
                            "reason_build",
                            "build",
                            "final_review",
                        }:
                            self.assertTrue((folder / template_path).exists(), f"{key}.templatePath does not exist")

                    for rel_path in step.get("expectedFiles") or []:
                        rel = str(rel_path).replace("\\", "/")
                        self.assertFalse(Path(rel).is_absolute(), f"{key}.expectedFiles cannot be absolute")
                        self.assertNotIn("..", Path(rel).parts, f"{key}.expectedFiles cannot traverse")
                        first = rel.split("/", 1)[0]
                        # Bare filenames are treated as output artifacts; prefixed files must stay in known workflow dirs.
                        if "/" in rel:
                            self.assertIn(first, allowed_first_segments, f"{key}.expectedFiles has unsupported prefix")

                    if step.get("type") == "gate":
                        self.assertTrue(step.get("function") or step.get("filename") or step.get("outputFile"), f"{key} gate needs a function or artifact")

    def test_system_controlled_qwen_has_expected_order_and_gates(self) -> None:
        workflow = workflow_config_service.system_workflow_with_folder()
        self.assertEqual([step["key"] for step in workflow["steps"]], SYSTEM_STEP_ORDER)
        gates = {step["key"]: step for step in workflow["steps"] if step.get("type") == "gate"}
        self.assertEqual(set(gates), {"spec_gate", "todo_gate", "final_gate"})
        for gate in gates.values():
            self.assertEqual(gate.get("function"), "require_status_pass")
            self.assertTrue(gate.get("retryFromStepKey"))


class StoreAndStateMachineTests(unittest.IsolatedAsyncioTestCase):
    def _store(self, path: Path, default_project: Path) -> Store:
        return Store(path, default_project_path=lambda: str(default_project), default_steps=lambda: [])

    def test_store_load_save_and_corrupted_json_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            store = self._store(store_path, Path(tmp))
            empty = store.load_sync()
            self.assertEqual(empty, {"sessions": [], "messages": [], "runs": [], "workflow_configs": []})

            data = {
                "sessions": [{"id": "s1", "project_path": str(tmp)}],
                "messages": [],
                "runs": [
                    {
                        "id": "r1",
                        "session_id": "s1",
                        "workspace": str(Path(tmp) / "run"),
                        "steps": [{"key": "step_a"}],
                    }
                ],
            }
            store.save_sync(data)
            loaded = store.load_sync()
            self.assertEqual(loaded["sessions"][0]["qwen_session_id"], "s1")
            self.assertEqual(loaded["runs"][0]["qwen_session_id"], "s1")
            self.assertEqual(loaded["runs"][0]["steps"][0]["status"], "pending")
            self.assertEqual(loaded["runs"][0]["steps"][0]["retry_count"], 0)

            store_path.write_text("{ broken json", encoding="utf-8")
            recovered = store.load_sync()
            self.assertEqual(recovered, {"sessions": [], "messages": [], "runs": [], "workflow_configs": []})
            self.assertTrue(list(Path(tmp).glob("store.corrupt-*.json")))

    async def test_step_state_machine_transitions_and_reset_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_workspace = Path(tmp) / "run"
            (run_workspace / ".workflow").mkdir(parents=True)
            (run_workspace / "output").mkdir()
            (run_workspace / "input").mkdir()
            (run_workspace / "prompts").mkdir()
            (run_workspace / ".workflow" / "run-log.md").write_text("", encoding="utf-8")
            steps = [
                {"key": "spec", "status": "pending", "started_at": None, "ended_at": None, "error": None, "retry_count": 0},
                {"key": "todo", "status": "pending", "started_at": None, "ended_at": None, "error": None, "retry_count": 0},
                {"key": "build", "status": "pending", "started_at": None, "ended_at": None, "error": None, "retry_count": 0},
            ]
            store = self._store(Path(tmp) / "store.json", Path(tmp))
            store.save_sync(
                {
                    "sessions": [{"id": "s1", "project_path": str(tmp), "qwen_session_id": "s1"}],
                    "messages": [],
                    "workflow_configs": [],
                    "runs": [
                        {
                            "id": "r1",
                            "session_id": "s1",
                            "workspace": str(run_workspace),
                            "project_path": str(tmp),
                            "status": "queued",
                            "steps": steps,
                        }
                    ],
                }
            )
            state = RunState(store, DummyBus())

            await state.set_step("r1", "spec", "running")
            run = await state.get_run_record("r1")
            self.assertEqual(run["steps"][0]["status"], "running")
            self.assertIsNone(run["steps"][0]["error"])
            self.assertIsNotNone(run["steps"][0]["started_at"])

            await state.set_step("r1", "spec", "passed")
            await state.set_step("r1", "todo", "failed", "review rejected")
            run = await state.get_run_record("r1")
            self.assertEqual([step["status"] for step in run["steps"]], ["passed", "failed", "pending"])
            self.assertEqual(run["steps"][1]["error"], "review rejected")

            await state.increment_step_retry("r1", "todo")
            self.assertEqual(await state.get_step_retry_count("r1", "todo"), 1)
            await state.reset_steps_from("r1", 1)
            run = await state.get_run_record("r1")
            self.assertEqual(run["status"], "queued")
            self.assertEqual([step["status"] for step in run["steps"]], ["passed", "pending", "pending"])
            self.assertIsNone(run["steps"][1]["error"])
            self.assertEqual(run["steps"][1]["retry_count"], 1)


class QwenRunnerUnitTests(unittest.TestCase):
    def _with_env(self, **updates: str):
        class EnvCtx:
            def __enter__(self_inner):
                self_inner.old = {key: os.environ.get(key) for key in updates}
                os.environ.update(updates)

            def __exit__(self_inner, exc_type, exc, tb):
                for key, value in self_inner.old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        return EnvCtx()

    def test_qwen_runner_command_args_env_and_session(self) -> None:
        with self._with_env(QWEN_BIN="qwen-test", QWEN_REUSE_SESSION="1", QWEN_BARE="1", QWEN_AUTH_TYPE="oauth"):
            client = QwenCliClient({"reuse_session": False})
            self.assertEqual(
                client.command("abc", include_prompt_flag=True),
                ["qwen-test", "--bare", "--session-id", "abc", "--chat-recording", "--auth-type", "oauth", "-p"],
            )

    def test_qwen_runner_timeout_and_non_zero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._with_env(QWEN_BIN="qwen-test", QWEN_MOCK="0"):
            client = QwenCliClient({})
            with patch("app.runtime_modules.qwen.shutil.which", return_value="/bin/qwen-test"):
                with patch("app.runtime_modules.qwen.subprocess.run", side_effect=subprocess.TimeoutExpired("qwen", 2)):
                    with self.assertRaisesRegex(WorkflowError, "timed out after 2"):
                        client.run("prompt", Path(tmp), timeout_sec=2)

                failed = subprocess.CompletedProcess(args=["qwen-test"], returncode=7, stdout="", stderr="boom")
                with patch("app.runtime_modules.qwen.subprocess.run", return_value=failed):
                    with self.assertRaisesRegex(WorkflowError, "boom"):
                        client.run("prompt", Path(tmp))

    def test_qwen_runner_retries_without_session_when_session_is_in_use(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="session already in use")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp, self._with_env(QWEN_BIN="qwen-test", QWEN_MOCK="0", QWEN_REUSE_SESSION="1"):
            client = QwenCliClient({})
            with patch("app.runtime_modules.qwen.shutil.which", return_value="/bin/qwen-test"), patch("app.runtime_modules.qwen.subprocess.run", side_effect=fake_run):
                self.assertEqual(client.run("prompt", Path(tmp), qwen_session_id="s1"), "ok")

        self.assertIn("--session-id", calls[0])
        self.assertNotIn("--session-id", calls[1])


class PromptAndArtifactFunctionTests(unittest.TestCase):
    def test_prompt_templates_require_expected_outputs_and_context(self) -> None:
        prompts = Path("data/ai-workflow/steps/system-controlled-qwen")
        spec_prompt = (prompts / "01_spec.md").read_text(encoding="utf-8")
        todo_prompt = (prompts / "03_todo.md").read_text(encoding="utf-8")
        build_prompt = (prompts / "05_build.md").read_text(encoding="utf-8")
        review_prompt = (prompts / "02_review_spec.md").read_text(encoding="utf-8")
        final_prompt = (prompts / "06_final_review.md").read_text(encoding="utf-8")

        self.assertIn("output/spec.md", spec_prompt)
        self.assertIn("## Acceptance Criteria", spec_prompt)
        self.assertIn("{{requirement}}", spec_prompt)
        self.assertIn("output/todo.md", todo_prompt)
        self.assertIn("TODO-001", todo_prompt)
        self.assertIn("TEST-001", todo_prompt)
        self.assertIn("Project Path: {{project_path}}", build_prompt)
        self.assertIn("Output only FILE/CONTENT/END_FILE blocks", build_prompt)
        self.assertIn("Do not create tests in this step", build_prompt)
        self.assertIn("Status: PASS", review_prompt)
        self.assertIn("Status: FAIL", review_prompt)
        self.assertIn("Status: PASS", final_prompt)

    def test_prompt_builder_injects_requirement_project_profile_and_failure_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_dir = root / "project"
            project_dir.mkdir()
            project_dir.joinpath("app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
            run_dir = root / "run"
            for folder in ["output", "input", "prompts", ".workflow"]:
                (run_dir / folder).mkdir(parents=True)
            (run_dir / "requirement.md").write_text("新增 hello feature", encoding="utf-8")
            (run_dir / "input" / "answers.md").write_text("", encoding="utf-8")
            (run_dir / "input" / "guidance.md").write_text("", encoding="utf-8")
            (run_dir / "input" / "failure-feedback.md").write_text(
                "## Retry Feedback for generate_spec\n\nError message to fix:\n\nmissing AC-001\n", encoding="utf-8"
            )
            workflow = workflow_config_service.system_workflow_with_folder()
            run = {
                "id": "r1",
                "workspace": str(run_dir),
                "project_path": str(project_dir),
                "workflow_id": "system-controlled-qwen",
                "workflow_folder": "system-controlled-qwen",
                "skill_root": "",
                "steps": initial_steps(workflow["steps"]),
            }

            result = PromptBuilder().build(run, "generate_spec", "01_spec.md", allow_interaction=False, agent_name="qwen")
            self.assertIn("新增 hello feature", result.prompt)
            self.assertIn(f"Project Path: {project_dir}", result.prompt)
            self.assertIn("Detected project profile", result.prompt)
            self.assertIn("Previous Failure Feedback", result.prompt)
            self.assertIn("missing AC-001", result.prompt)
            self.assertTrue((run_dir / "prompts" / "generate_spec.md").exists())

    def test_build_prompt_hardening_blocks_test_file_generation(self) -> None:
        hardened = AgentStepRunner._harden_prompt_for_step("build", "Base prompt")
        self.assertIn("Build output guard", hardened)
        self.assertIn("Do not write paths under tests/", hardened)
        self.assertIn("at least one non-test production file", hardened)
        test_hardened = AgentStepRunner._harden_prompt_for_step("generate_tests", "Base prompt")
        self.assertIn("Workspace safety guard", test_hardened)
        self.assertIn("Generate Tests output guard", test_hardened)
        self.assertIn("write only tests/test_*.py", test_hardened)

    def test_artifact_function_rejects_empty_or_invalid_files(self) -> None:
        service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "output"
            output_dir.mkdir()
            (output_dir / "spec.md").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "empty"):
                service.validate_spec(output_dir)

            (output_dir / "spec.md").write_text(VALID_SPEC, encoding="utf-8")
            service.validate_spec(output_dir)

            (output_dir / "todo.md").write_text("## Todo List\n- TODO-001 only\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "missing sections"):
                service.validate_todo(output_dir)

            (output_dir / "todo.md").write_text(VALID_TODO, encoding="utf-8")
            service.validate_todo(output_dir)

            (output_dir / "review.md").write_text("Status: FAIL\n", encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "Status: PASS"):
                service.require_status(output_dir / "review.md", "PASS")
            (output_dir / "review.md").write_text("Status: PASS\n", encoding="utf-8")
            service.require_status(output_dir / "review.md", "PASS")

    def test_file_extractors_reject_invalid_test_and_build_outputs(self) -> None:
        test_files = extract_build_files("FILE: app.py\nCONTENT:\nprint('bad')\nEND_FILE\n")
        with self.assertRaisesRegex(WorkflowError, "generate_tests can only write"):
            validate_generated_test_files(test_files)

        build_files = extract_build_files("FILE: tests/test_bad.py\nCONTENT:\ndef test_bad(): pass\nEND_FILE\n")
        with self.assertRaisesRegex(WorkflowError, "build must not create"):
            validate_build_files_are_not_tests(build_files)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkflowError, "unsafe file path"):
                apply_extracted_files(Path(tmp), [("../escape.py", "print('x')\n")])
            self.assertFalse((Path(tmp).parent / "escape.py").exists())


class ApiWorkflowContractTests(unittest.TestCase):
    def _patch_workflow(self, workflow: dict):
        original_get_workflow = workflow_config_service.get_workflow

        async def fake_get_workflow(workflow_id: str) -> dict:
            if workflow_id == workflow["id"]:
                return workflow
            return await original_get_workflow(workflow_id)

        return patch("app.services.workflow_service.workflow_config_service.get_workflow", side_effect=fake_get_workflow)

    def _simple_workflow(self, workflow_id: str = "api-contract-workflow") -> dict:
        return {
            "id": workflow_id,
            "kind": "custom",
            "name": workflow_id,
            "folderName": "system-controlled-qwen",
            "skillRoot": "",
            "steps": [
                {
                    "id": "api-step",
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

    def test_api_contract_workflow_run_reset_retry_and_errors(self) -> None:
        workflow = self._simple_workflow()

        def qwen_response(prompt: str) -> str:
            return "Status: DONE\n\nAPI artifact.\n"

        old_mock = os.environ.get("QWEN_MOCK")
        os.environ["QWEN_MOCK"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp, self._patch_workflow(workflow), patch(
                "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
            ):
                project_dir = Path(tmp)
                project_dir.joinpath("seed.py").write_text("VALUE = 1\n", encoding="utf-8")
                with TestClient(app) as client:
                    session_response = client.post("/api/sessions", json={"title": "API Contract", "project_path": str(project_dir)})
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()

                    missing_requirement = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={"workflow_id": workflow["id"], "project_path": str(project_dir)},
                    )
                    self.assertEqual(missing_requirement.status_code, 400)
                    self.assertIn("Requirement is required", missing_requirement.text)

                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={"workflow_id": workflow["id"], "project_path": str(project_dir), "requirement": "api contract"},
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = run_response.json()
                    deadline = time.time() + 5
                    while time.time() < deadline:
                        latest = client.get(f"/api/workflow-runs/{run['id']}").json()
                        if latest["status"] in {"done", "failed"}:
                            run = latest
                            break
                        time.sleep(0.05)
                    self.assertEqual(run["status"], "done", run.get("error"))

                    latest = client.get(f"/api/sessions/{session['id']}/workflow-runs/latest")
                    self.assertEqual(latest.status_code, 200)
                    self.assertEqual(latest.json()["id"], run["id"])

                    artifacts = client.get(f"/api/workflow-runs/{run['id']}/artifacts")
                    self.assertEqual(artifacts.status_code, 200)
                    self.assertTrue(any(item["name"] == "raw.md" for item in artifacts.json()))

                    bad_retry = client.post(f"/api/workflow-runs/{run['id']}/retry", json={"step_key": "missing_step"})
                    self.assertEqual(bad_retry.status_code, 400)
                    self.assertIn("Unknown step", bad_retry.text)

                    retry = client.post(f"/api/workflow-runs/{run['id']}/retry", json={"step_key": "raw_artifact"})
                    self.assertEqual(retry.status_code, 200, retry.text)
                    self.assertEqual(retry.json()["id"], run["id"])

                    reset = client.post(f"/api/sessions/{session['id']}/reset")
                    self.assertEqual(reset.status_code, 200, reset.text)
                    self.assertEqual(reset.json()["id"], session["id"])
                    self.assertIsNone(client.get(f"/api/sessions/{session['id']}/workflow-runs/latest").json())

                    self.assertEqual(client.get("/api/workflow-runs/not-found").status_code, 404)
                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock


class SecurityBoundaryUnitTests(unittest.TestCase):
    def test_security_rejects_path_traversal_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            project.mkdir()
            run = {"workspace": str(workspace), "project_path": str(project)}

            unsafe_steps = [
                {"config": {"expectedFiles": ["../outside.md"]}},
                {"config": {"expectedFiles": [str(Path(tmp) / "outside.md")]}},
                {"config": {"expectedFiles": ["output/../../outside.md"]}},
            ]
            for step in unsafe_steps:
                rel = expected_files(step)[0]
                with self.subTest(rel=rel):
                    with self.assertRaisesRegex(WorkflowError, "Unsafe expected file path"):
                        expected_file_candidates(run, rel)

            candidates = expected_file_candidates(run, "result.md")
            self.assertEqual(candidates[:3], [workspace / "output" / "result.md", workspace / "result.md", project / "result.md"])

    def test_security_apply_extracted_files_blocks_absolute_qwen_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            absolute_target = Path(tmp) / "absolute.py"
            with self.assertRaisesRegex(WorkflowError, "unsafe file path"):
                apply_extracted_files(project, [(str(absolute_target), "print('bad')\n")])
            self.assertFalse(absolute_target.exists())


if __name__ == "__main__":
    unittest.main()
