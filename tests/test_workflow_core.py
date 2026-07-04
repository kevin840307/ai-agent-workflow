from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import (
    apply_extracted_files,
    classify_test_retry_target,
    extract_build_files,
    render_project_index_markdown,
    validate_build_files_do_not_overwrite_validation_scripts,
)
from app.services import workflow_asset_service, workflow_config_service
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.workflow_runtime.actions import WorkflowActions
from app.workflow_runtime.agents import ADAPTER_FACTORIES, create_agent_manager
from app.workflow_runtime.retry_policy import retry_target_for_failure, retry_target_for_step
from app.workflow_runtime.run_profiles import apply_run_profile, normalize_run_profile
from app.workflow_runtime.step_config import initial_steps


class WorkflowCoreTests(unittest.TestCase):
    def test_prepare_project_accepts_direct_architecture_markdown(self) -> None:
        class FakeAgentRunner:
            async def run(self, run, step_key, prompt_name, artifact, **_kwargs):
                text = (
                    "# Architecture\n\n"
                    "## Project Summary\n- Current purpose: config workflow.\n\n"
                    "## Runtime Agent Settings\n- Qwen project settings: missing at `.qwen/settings.json`\n\n"
                    "## Detected Stack\n- Primary language: YAML\n\n"
                    "## Current Structure\n- Source layout: config/\n\n"
                    "## Implementation Rules\n- Keep changes small.\n"
                )
                output = Path(run["workspace"]) / "output"
                output.mkdir(parents=True, exist_ok=True)
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
            (project / "config").mkdir()
            (project / "config" / "users.yaml").write_text("users: []\n", encoding="utf-8")
            actions = WorkflowActions(agent_runner=FakeAgentRunner(), functions=None, log=log, refresh_artifacts=refresh)

            asyncio.run(actions.prepare_project_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project), "steps": [{"key": "run_external_validation", "config": {"fallbackValidationScripts": ["validation.py"]}}]}))

            self.assertIn("Primary language: YAML", (project / "architecture.md").read_text(encoding="utf-8"))

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

    def test_file_blocks_cannot_escape_project_path(self) -> None:
        files = extract_build_files("FILE: ../escape.py\nCONTENT:\nprint('bad')\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkflowError):
                apply_extracted_files(Path(tmp), files)

    def test_file_blocks_cannot_use_placeholder_relative_paths(self) -> None:
        files = extract_build_files("FILE: relative/path.ext\nCONTENT:\nplaceholder\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkflowError, "placeholder relative/path"):
                apply_extracted_files(Path(tmp), files)

    def test_file_blocks_cannot_use_common_placeholder_paths(self) -> None:
        files = extract_build_files("FILE: path_to_output.py\nCONTENT:\nplaceholder\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkflowError, "placeholder output path"):
                apply_extracted_files(Path(tmp), files)

    def test_build_cannot_overwrite_existing_validation_script(self) -> None:
        files = extract_build_files("FILE: validation.py\nCONTENT:\nprint('fake pass')\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "validation.py").write_text("raise SystemExit(1)\n", encoding="utf-8")

            with self.assertRaisesRegex(WorkflowError, "validation scripts"):
                validate_build_files_do_not_overwrite_validation_scripts(project, files, fallback_scripts=["validation.py"])

    def test_build_can_create_non_validation_artifacts_when_validator_exists(self) -> None:
        files = extract_build_files("FILE: generated/users.yaml\nCONTENT:\nusers: []\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "validation.py").write_text("print('ok')\n", encoding="utf-8")

            validate_build_files_do_not_overwrite_validation_scripts(project, files, fallback_scripts=["validation.py"])
            written = apply_extracted_files(project, files)

            self.assertEqual([path.relative_to(project).as_posix() for path in written], ["generated/users.yaml"])

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

            with self.assertRaisesRegex(WorkflowError, "production FILE/CONTENT/END_FILE"):
                asyncio.run(actions.build_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project), "steps": [{"key": "run_external_validation", "config": {"fallbackValidationScripts": ["validation.py"]}}]}))


    def test_generate_tests_retry_removes_stale_workflow_generated_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            tests_dir = project / "tests"
            tests_dir.mkdir()
            stale = tests_dir / "test_old.py"
            keep = tests_dir / "test_keep.py"
            stale.write_text("def test_old(): pass\n", encoding="utf-8")
            keep.write_text("def test_keep(): pass\n", encoding="utf-8")

            WorkflowActions._remove_stale_generated_tests(
                project,
                [("tests/test_old.py", ""), ("tests/test_keep.py", "")],
                [("tests/test_keep.py", "")],
            )

            self.assertFalse(stale.exists())
            self.assertTrue(keep.exists())

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
                "build did not return any production FILE/CONTENT/END_FILE blocks.\n",
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
                    WorkflowError("build did not return any production FILE/CONTENT/END_FILE blocks."),
                )
            )

    def test_implementation_review_writes_task_manifest_for_small_task_order(self) -> None:
        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            workspace.mkdir()
            output.mkdir()
            (workspace / "requirement.md").write_text("Build a small feature", encoding="utf-8")
            (output / "todo.md").write_text(
                "# Todo\n\n"
                "Status: READY\n\n"
                "## Requirement\n- Build a small feature.\n\n"
                "## Task Index\n"
                "| ID | Task | Acceptance Criteria | Depends On |\n"
                "| --- | --- | --- | --- |\n"
                "| TASK-001 | Create production change | AC-001 | None |\n"
                "| TASK-002 | Integrate behavior | AC-002 | TASK-001 |\n\n"
                "## Tasks\n\n"
                "### TASK-001: Create production change\n"
                "- Acceptance Criteria:\n  - AC-001: production code exists.\n\n"
                "### TASK-002: Integrate behavior\n"
                "- Acceptance Criteria:\n  - AC-002: assembled behavior works.\n\n"
                "## Execution SOP\n- Step 1: Build production code only.\n\n"
                "## Acceptance & Stop Conditions\n- Stop condition: tests and external validation pass.\n\n"
                "## External Validation\n- Run validation when present.\n",
                encoding="utf-8",
            )
            actions = WorkflowActions(agent_runner=None, functions=None, log=log, refresh_artifacts=refresh)

            asyncio.run(actions.implementation_review_step({"id": "run-1", "workspace": str(workspace)}))

            manifest = (output / "task-manifest.md").read_text(encoding="utf-8")
            self.assertIn("Status: READY", manifest)
            self.assertIn("TASK-001", manifest)
            self.assertIn("TASK-002", manifest)
            self.assertIn("Repeated errors are allowed", manifest)

    def test_implementation_review_repairs_todo_that_targets_validation_script(self) -> None:
        async def log(_run, _message):
            return None

        async def refresh(_run_id):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = project / ".ai-workflow" / "runs" / "session-1" / "run-1"
            output = workspace / "output"
            output.mkdir(parents=True)
            (project / "validation.py").write_text("print('external validation ok')\n", encoding="utf-8")
            (workspace / "requirement.md").write_text("請用 Python 寫泡沫排序", encoding="utf-8")
            (output / "todo.md").write_text(
                "# Todo\n\n"
                "Status: READY\n\n"
                "## Requirement\n- Implement the requested Python behavior.\n\n"
                "## Task Index\n"
                "| ID | Task | Acceptance Criteria | Depends On |\n"
                "| --- | --- | --- | --- |\n"
                "| TASK-001 | Modify validation.py | AC-001 | None |\n\n"
                "## Tasks\n\n"
                "### TASK-001: Modify validation.py\n"
                "- Files: validation.py\n"
                "- Acceptance Criteria:\n  - AC-001: validation.py includes the implementation.\n\n"
                "## Execution SOP\n- Step 1: Build production code only.\n\n"
                "## Acceptance & Stop Conditions\n- Stop condition: tests and external validation pass.\n\n"
                "## External Validation\n- Run validation.py after tests.\n",
                encoding="utf-8",
            )
            actions = WorkflowActions(agent_runner=None, functions=None, log=log, refresh_artifacts=refresh)

            asyncio.run(
                actions.implementation_review_step(
                    {"id": "run-1", "workspace": str(workspace), "project_path": str(project), "steps": [{"key": "run_external_validation", "config": {"fallbackValidationScripts": ["validation.py"]}}]}
                )
            )

            repaired = (output / "todo.md").read_text(encoding="utf-8")
            task_context = repaired.split("## External Validation", 1)[0]
            self.assertNotIn("validation.py", task_context)
            self.assertIn("Implement production change", repaired)
            review = (output / "implementation-review.md").read_text(encoding="utf-8")
            self.assertIn("validation scripts", review)

    def test_general_auto_development_compiles_split_task_todo_files(self) -> None:
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
            (workspace / "requirement.md").write_text("Add config helper", encoding="utf-8")
            (output / "todo.md").write_text(
                "# Todo\n\n"
                "Status: READY\n\n"
                "## Requirement\n- Add config helper.\n\n"
                "## Task Index\n"
                "| ID | Task | Acceptance Criteria | Depends On |\n"
                "| --- | --- | --- | --- |\n"
                "| TASK-001 | Add loader | AC-001 | None |\n"
                "| TASK-002 | Add saver | AC-002 | TASK-001 |\n\n"
                "## Task Assembly Plan\n- Build order: TASK-001 then TASK-002.\n\n"
                "## Tasks\n\n"
                "### TASK-001: Add loader\n"
                "- Goal: Implement load_config.\n"
                "- Acceptance Criteria:\n  - AC-001: load_config reads JSON.\n\n"
                "### TASK-002: Add saver\n"
                "- Goal: Implement save_config.\n"
                "- Acceptance Criteria:\n  - AC-002: save_config writes JSON.\n\n"
                "## Execution SOP\n- Step 1: Build production code only.\n\n"
                "## Acceptance & Stop Conditions\n- Stop condition: tests and external validation pass.\n\n"
                "## External Validation\n- If no validation script is configured or found, skip with PASS.\n",
                encoding="utf-8",
            )
            actions = WorkflowActions(agent_runner=None, functions=None, log=log, refresh_artifacts=refresh)

            asyncio.run(actions.implementation_review_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project), "workflow_id": "general-auto-development", "steps": []}))

            task1 = output / "todos" / "TASK-001.md"
            task2 = output / "todos" / "TASK-002.md"
            self.assertTrue(task1.is_file())
            self.assertTrue(task2.is_file())
            self.assertIn("Add loader", task1.read_text(encoding="utf-8"))
            self.assertIn("Add saver", task2.read_text(encoding="utf-8"))
            self.assertIn("output/todos/TASK-001.md", (output / "todos" / "INDEX.md").read_text(encoding="utf-8"))
            self.assertIn("output/todos/TASK-xxx.md", (output / "implementation-review.md").read_text(encoding="utf-8"))

    def test_adaptive_auto_workflow_loads_simple_review_loop(self) -> None:
        workflow = workflow_asset_service.load_workflow_asset("adaptive-auto-workflow")
        keys = [step["key"] for step in workflow["steps"]]
        self.assertEqual(
            keys,
            [
                "prepare_project",
                "plan_tasks",
                "implementation_review",
                "build",
                "sub_agent_review",
                "generate_tests",
                "run_test",
                "run_external_validation",
                "final_review",
                "final_gate",
            ],
        )
        review = next(step for step in workflow["steps"] if step["key"] == "sub_agent_review")
        self.assertEqual(review["type"], "review")
        self.assertEqual(review["reviewMode"], "multi_agent")
        self.assertEqual(review["retryFromStepKey"], "build")
        self.assertGreaterEqual(len(review.get("reviewers") or []), 3)


if __name__ == "__main__":
    unittest.main()
