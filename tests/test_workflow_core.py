from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import (
    classify_test_retry_target,
    render_project_index_markdown,
    validate_build_files_do_not_overwrite_validation_scripts,
)
from app.services import workflow_asset_service, workflow_config_service
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.workflow_runtime.actions import WorkflowActions
from app.workflow_runtime.agents import ADAPTER_FACTORIES, create_agent_manager
from app.workflow_runtime.functions import WorkflowFunctionService
from app.workflow_runtime.retry_policy import retry_target_for_failure, retry_target_for_step
from app.workflow_runtime.run_profiles import apply_run_profile, normalize_run_profile
from app.workflow_runtime.step_config import initial_steps


class WorkflowCoreTests(unittest.TestCase):


    def test_catalog_function_ids_are_executable_or_runtime_special_cases(self) -> None:
        function_ids = {item["id"] for item in workflow_asset_service.function_catalog()["functions"]}
        executable_or_special = set(PYTHON_FUNCTIONS) | {"consensus_agent"}
        missing = sorted(
            function_id
            for function_id in function_ids - executable_or_special
            if not workflow_asset_service.resolve_function_reference(function_id)
        )
        self.assertEqual(missing, [])

    def test_retry_policy_uses_configured_retry_target(self) -> None:
        steps = initial_steps(
            [
                {"key": "build", "type": "ai", "maxRetries": 3},
                {"key": "run_test", "type": "python", "function": "run_pytest", "retryFromStepKey": "build"},
            ]
        )

        self.assertEqual(retry_target_for_step(steps[1], steps, 1), "build")

    def test_run_test_retry_classification_can_route_to_tests_or_build(self) -> None:
        steps = initial_steps(
            [
                {"key": "generate_tests", "type": "ai", "maxRetries": 3},
                {"key": "build", "type": "ai", "maxRetries": 3},
                {"key": "run_test", "type": "python", "function": "run_pytest", "retryFromStepKey": "build"},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "test-result.md").write_text("ImportError while importing test module", encoding="utf-8")
            run = {"project_path": tmp}
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "generate_tests")


            (output_dir / "test-result.md").write_text(
                "E       NameError: name 'os' is not defined\nFAILED tests/test_yaml_crud.py::test_output",
                encoding="utf-8",
            )
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "generate_tests")

            production_file = Path(tmp) / "src" / "tool.py"
            production_file.parent.mkdir()
            production_file.write_text("def main(): pass\n", encoding="utf-8")
            (output_dir / "test-result.md").write_text(
                f"NameError: name 'yaml' is not defined\n  File \"{production_file}\", line 6, in update_users",
                encoding="utf-8",
            )
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "build")

            (output_dir / "test-result.md").write_text("AssertionError: wrong result", encoding="utf-8")
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "build")

    def test_task_owner_uses_task_goal_before_downstream_validation_text(self) -> None:
        actions = WorkflowActions(agent_runner=None, functions=None, log=None, refresh_artifacts=None)
        todo = """# Todo

Status: READY

## Tasks

### TASK-001: Implement production change
- Goal: Implement the requested feature.
- Acceptance Criteria:
  - AC-001: The feature works.
- Validation:
  - Covered by Generate Tests, Run Test, and External Validation.
"""

        self.assertEqual(actions._task_owner(todo, "TASK-001"), "build")

    def test_generic_retry_feedback_prevents_task_loop_skip(self) -> None:
        feedback = """## Retry Feedback for auto_generation

- Failure source: run_external_validation
- Error: External validation failed because generated imports are invalid.
"""

        self.assertTrue(WorkflowActions._feedback_is_generic_for_task_loop(feedback))
        self.assertFalse(WorkflowActions._latest_feedback_mentions_task(feedback, "TASK-001"))






    def test_build_step_rejects_missing_production_file_blocks_without_domain_fallback(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                text = "Status: PASS\n\nNo file blocks.\n"
                (output / artifact).write_text(text, encoding="utf-8")
                return text

        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            project.mkdir()
            (workspace / "output").mkdir(parents=True)
            (workspace / "requirement.md").write_text("Create a config output", encoding="utf-8")
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)

            with self.assertRaisesRegex(WorkflowError, "directly create or modify project files"):
                asyncio.run(actions.build_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project), "steps": [{"key": "run_external_validation", "config": {"fallbackValidationScripts": ["validation.py"]}}]}))

    def test_build_step_rejects_documentation_only_direct_edits_by_default(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                project = Path(run["project_path"])
                (project / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                (output / artifact).write_text("# Build Result\n\nStatus: READY\n", encoding="utf-8")
                return "# Build Result\n\nStatus: READY\n"

        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            project.mkdir()
            (workspace / "output").mkdir(parents=True)
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)
            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "steps": [{"key": "build", "config": {"requireSubstantiveBuild": True, "allowDocumentationOnlyBuild": False}}],
            }

            with self.assertRaisesRegex(WorkflowError, "requires a concrete project artifact"):
                asyncio.run(actions.build_step(run))

    def test_build_step_can_allow_documentation_only_direct_edits_by_config(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                project = Path(run["project_path"])
                (project / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                (output / artifact).write_text("# Build Result\n\nStatus: READY\n", encoding="utf-8")
                return "# Build Result\n\nStatus: READY\n"

        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            project.mkdir()
            (workspace / "output").mkdir(parents=True)
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)
            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "steps": [{"key": "build", "config": {"requireSubstantiveBuild": True, "allowDocumentationOnlyBuild": True}}],
            }

            asyncio.run(actions.build_step(run))
            self.assertTrue((project / "architecture.md").exists())



    def test_generate_tests_requires_direct_test_file_edits(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                text = "Status: PASS\n\nNo direct test file edits.\n"
                (output / artifact).write_text(text, encoding="utf-8")
                return text

        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            project.mkdir()
            (workspace / "output").mkdir(parents=True)
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)

            with self.assertRaisesRegex(WorkflowError, "directly create or modify pytest files"):
                asyncio.run(actions.generate_tests_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project)}))

    def test_generate_tests_accepts_existing_project_tests_after_retry(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
                text = "Status: PASS\n\nTests already exist from a previous retry.\n"
                (output / artifact).write_text(text, encoding="utf-8")
                return text

        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            tests = project / "tests"
            tests.mkdir(parents=True)
            (workspace / "output").mkdir(parents=True)
            (tests / "test_existing.py").write_text("def test_existing():\n    assert True\n", encoding="utf-8")
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)

            asyncio.run(actions.generate_tests_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project)}))

            text = (workspace / "output" / "test-plan.md").read_text(encoding="utf-8")
            self.assertIn("tests/test_existing.py", text)

    def test_fresh_session_respects_step_keep_same_session_config(self) -> None:
        run = {
            "steps": [
                {"key": "build", "config": {"keepSameSession": True}},
                {"key": "generate_tests", "config": {"keepSameSession": False}},
            ]
        }

        self.assertFalse(WorkflowActions._fresh_session_for_step(run, "build"))
        self.assertTrue(WorkflowActions._fresh_session_for_step(run, "generate_tests"))

    def test_workflow_bundle_paths_are_normalized_inside_asset_dirs(self) -> None:
        self.assertEqual(
            workflow_config_service.safe_bundle_relative_path("custom.md", "prompts/default.md"),
            "prompts/custom.md",
        )
        self.assertEqual(
            workflow_config_service.safe_bundle_relative_path("../bad.md", "prompts/default.md"),
            "prompts/bad.md",
        )

    def test_agent_manager_supports_opencode_provider_shape(self) -> None:
        self.assertIn("qwen_cli", ADAPTER_FACTORIES)
        self.assertIn("opencode_cli", ADAPTER_FACTORIES)
        manager = create_agent_manager(
            {
                "agents": {
                    "default": "opencode",
                    "providers": {
                        "opencode": {"type": "opencode_cli", "bin": "opencode", "mode": "run"},
                    },
                },
                "qwen": {},
            }
        )

        self.assertEqual(manager.default_agent_name(), "opencode")
        self.assertIn("opencode", manager.available_agent_names())
        self.assertEqual(manager.resolve(agent_name="opencode").name, "opencode")
        self.assertEqual(manager.resolve().name, "opencode")


    def test_project_index_is_python_generated_and_mentions_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")

            index = render_project_index_markdown(project)

            self.assertIn("# Project Index", index)
            self.assertIn("Status: READY", index)
            self.assertIn("python -m pytest", index)
            self.assertIn("Agent writes must stay inside Project Path", index)
            self.assertIn("app.py", index)

    def test_structured_task_kind_routes_tests_out_of_build(self) -> None:
        actions = WorkflowActions(agent_runner=None, functions=None, log=None, refresh_artifacts=None)
        self.assertEqual(actions._task_owner_from_entry({"kind": "implementation"}), "build")
        self.assertEqual(actions._task_owner_from_entry({"kind": "test"}), "generate_tests")
        self.assertEqual(actions._task_owner_from_entry({"kind": "validation"}), "run_external_validation")
        parsed = actions._task_entries_from_manifest(
            "1. TASK-001 [kind=implementation]: Add code\n"
            "2. TASK-002 [kind=test]: Add tests\n",
            owner="build",
        )
        self.assertEqual([task["id"] for task in parsed], ["TASK-001"])

    def test_run_profile_deep_enables_thinking_without_extra_steps(self) -> None:
        steps = initial_steps(
            [
                {"key": "plan_tasks", "type": "ai", "maxRetries": 2},
                {"key": "build", "type": "ai", "maxRetries": 3},
                {"key": "run_test", "type": "python", "function": "run_pytest", "maxRetries": 1},
            ]
        )

        profiled = apply_run_profile(steps, "deep")

        self.assertEqual([step["key"] for step in profiled], ["plan_tasks", "build", "run_test"])
        self.assertTrue(next(step for step in profiled if step["key"] == "build")["thinking"])
        self.assertGreaterEqual(next(step for step in profiled if step["key"] == "build")["max_retries"], 12)
        self.assertEqual(normalize_run_profile("最高"), "deep")

    def test_executor_detects_same_retry_failure_as_informational_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "input").mkdir()
            (workspace / "input" / "failure-feedback.md").write_text(
                "## Retry Feedback for build\n\n"
                "### Error message to fix\n\n"
                "build did not directly create or modify production files under Project Path.\n",
                encoding="utf-8",
            )
            executor = __import__("app.workflow_runtime.executor", fromlist=["WorkflowExecutor"]).WorkflowExecutor(
                store=None,
                bus=None,
                actions=None,
                update_run=None,
                set_step=None,
                reset_steps_from=None,
                get_step_retry_count=None,
                increment_step_retry=None,
                append_failure_feedback=None,
                refresh_artifacts=None,
                log=None,
            )
            self.assertTrue(
                executor._same_failure_repeated(
                    {"workspace": str(workspace)},
                    "build",
                    WorkflowError("build did not directly create or modify production files under Project Path."),
                )
            )








    def test_adaptive_external_validation_skips_when_no_script_is_provided(self) -> None:
        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            functions = WorkflowFunctionService(log=log, refresh_artifacts=refresh)
            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "_current_step_config": {"fallbackValidationScripts": ["validation.py"]},
            }

            asyncio.run(functions.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: NOT_CONFIGURED", result)
            self.assertNotIn("Status: PASS", result)
            self.assertIn("Optional user validation was not configured", result)












if __name__ == "__main__":
    unittest.main()
