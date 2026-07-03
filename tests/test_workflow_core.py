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
    synthesize_yaml_crud_build_files,
    validate_build_files_do_not_overwrite_validation_scripts,
)
from app.services import workflow_asset_service, workflow_config_service
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.workflow_runtime.actions import WorkflowActions
from app.workflow_runtime.agents import ADAPTER_FACTORIES, create_agent_manager
from app.workflow_runtime.retry_policy import retry_target_for_failure, retry_target_for_step
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

            asyncio.run(actions.prepare_project_step({"id": "run-1", "workspace": str(workspace), "project_path": str(project)}))

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
                "E       assert None == [1, 2, 3]\nFAILED tests/test_bubble_sort.py::test_bubble_sort",
                encoding="utf-8",
            )
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "generate_tests")

            (output_dir / "test-result.md").write_text(
                "E       NameError: name 'os' is not defined\nFAILED tests/test_yaml_crud.py::test_output",
                encoding="utf-8",
            )
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "generate_tests")

            (output_dir / "test-result.md").write_text("AssertionError: wrong result", encoding="utf-8")
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "build")

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

    def test_build_cannot_overwrite_existing_validation_script(self) -> None:
        files = extract_build_files("FILE: validation.py\nCONTENT:\nprint('fake pass')\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "validation.py").write_text("raise SystemExit(1)\n", encoding="utf-8")

            with self.assertRaisesRegex(WorkflowError, "validation scripts"):
                validate_build_files_do_not_overwrite_validation_scripts(project, files)

    def test_build_can_create_non_validation_artifacts_when_validator_exists(self) -> None:
        files = extract_build_files("FILE: generated/users.yaml\nCONTENT:\nusers: []\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "validation.py").write_text("print('ok')\n", encoding="utf-8")

            validate_build_files_do_not_overwrite_validation_scripts(project, files)
            written = apply_extracted_files(project, files)

            self.assertEqual([path.relative_to(project).as_posix() for path in written], ["generated/users.yaml"])

    def test_yaml_crud_build_fallback_synthesizes_requested_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "config").mkdir()
            (project / "config" / "users.yaml").write_text(
                "users:\n"
                "  - id: alice\n"
                "    role: reader\n"
                "    enabled: true\n"
                "  - id: bob\n"
                "    role: writer\n"
                "    enabled: false\n"
                "  - id: legacy\n"
                "    role: reader\n"
                "    enabled: false\n",
                encoding="utf-8",
            )
            (project / "config" / "crud.yaml").write_text(
                "source: config/users.yaml\n"
                "output: generated/users.yaml\n"
                "operations:\n"
                "  - action: update\n"
                "    id: bob\n"
                "    set:\n"
                "      role: admin\n"
                "      enabled: true\n"
                "  - action: create\n"
                "    value:\n"
                "      id: carol\n"
                "      role: reader\n"
                "      enabled: true\n"
                "  - action: delete\n"
                "    id: legacy\n",
                encoding="utf-8",
            )

            files = synthesize_yaml_crud_build_files(project)

            self.assertEqual([rel_path for rel_path, _content in files], ["generated/users.yaml"])
            self.assertIn("  - id: alice", files[0][1])
            self.assertIn("role: admin", files[0][1])
            self.assertIn("id: carol", files[0][1])
            self.assertNotIn("id: legacy", files[0][1])

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


if __name__ == "__main__":
    unittest.main()
