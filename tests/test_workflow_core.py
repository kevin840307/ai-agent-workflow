from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import apply_extracted_files, classify_test_retry_target, extract_build_files
from app.services import workflow_config_service
from app.workflow_function_catalog import AVAILABLE_WORKFLOW_FUNCTIONS
from app.workflow_functions import PYTHON_FUNCTIONS
from app.workflow_runtime.agents import ADAPTER_FACTORIES, create_agent_manager
from app.workflow_runtime.retry_policy import retry_target_for_failure, retry_target_for_step
from app.workflow_runtime.step_config import initial_steps


class WorkflowCoreTests(unittest.TestCase):
    def test_catalog_validator_ids_are_executable_or_runtime_special_cases(self) -> None:
        validator_ids = {item["id"] for item in AVAILABLE_WORKFLOW_FUNCTIONS["validators"]}
        executable_or_special = set(PYTHON_FUNCTIONS) | {"consensus_agent"}
        missing = sorted(validator_ids - executable_or_special)
        self.assertEqual(missing, [])

    def test_retry_policy_uses_configured_retry_target(self) -> None:
        steps = initial_steps(
            [
                {"key": "build", "type": "ai", "maxRetries": 3},
                {"key": "run_test", "type": "python", "validator": "run_pytest", "retryFromStepKey": "build"},
            ]
        )

        self.assertEqual(retry_target_for_step(steps[1], steps, 1), "build")

    def test_run_test_retry_classification_can_route_to_tests_or_build(self) -> None:
        steps = initial_steps(
            [
                {"key": "generate_tests", "type": "ai", "maxRetries": 3},
                {"key": "build", "type": "ai", "maxRetries": 3},
                {"key": "run_test", "type": "python", "validator": "run_pytest", "retryFromStepKey": "build"},
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "test-result.md").write_text("ImportError while importing test module", encoding="utf-8")
            run = {"project_path": tmp}
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "generate_tests")

            (output_dir / "test-result.md").write_text("AssertionError: wrong result", encoding="utf-8")
            self.assertEqual(retry_target_for_failure(run, steps[2], steps, 2, output_dir), "build")

    def test_file_blocks_cannot_escape_project_path(self) -> None:
        files = extract_build_files("FILE: ../escape.py\nCONTENT:\nprint('bad')\nEND_FILE\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkflowError):
                apply_extracted_files(Path(tmp), files)

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
