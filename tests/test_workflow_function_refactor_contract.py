from __future__ import annotations

import unittest
from pathlib import Path

import app.workflow_functions as workflow_functions
from app.workflow_function_modules import security_validation
from app.workflow_function_modules.registry import PYTHON_FUNCTIONS


class WorkflowFunctionRefactorContractTests(unittest.TestCase):
    def test_compatibility_facade_still_exports_existing_functions(self) -> None:
        expected = {
            "collect_security_context",
            "combine_security_candidates",
            "generate_security_report",
            "finalize_security_report",
            "require_status_pass",
            "run_pytest",
            "validate_security_candidates",
            "validate_security_report",
            "validate_spec",
            "validate_todo",
            "WorkflowFunctionContext",
            "WorkflowFunctionError",
        }

        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(workflow_functions, name), f"app.workflow_functions must still export {name}")

    def test_registry_keeps_same_callable_import_path_contract(self) -> None:
        expected_registry_names = {
            "collect_security_context",
            "combine_security_candidates",
            "generate_security_report",
            "finalize_security_report",
            "validate_security_candidates",
            "validate_security_report",
            "validate_spec",
            "validate_todo",
            "require_status_pass",
            "run_pytest",
        }
        self.assertEqual(expected_registry_names, set(PYTHON_FUNCTIONS))
        for name in expected_registry_names:
            with self.subTest(name=name):
                self.assertIs(PYTHON_FUNCTIONS[name], getattr(workflow_functions, name))

    def test_legacy_security_validation_import_path_is_a_facade(self) -> None:
        self.assertIs(
            security_validation.validate_security_candidates,
            workflow_functions.validate_security_candidates,
        )
        self.assertIs(
            security_validation.combine_security_candidates,
            workflow_functions.combine_security_candidates,
        )
        self.assertIs(
            security_validation.validate_security_report,
            workflow_functions.validate_security_report,
        )

    def test_workflow_function_files_stay_modular(self) -> None:
        limits = {
            "app/workflow_functions.py": 200,
            "app/workflow_function_modules/security_validation.py": 120,
            "app/workflow_function_modules/security_common.py": 1100,
            "app/workflow_function_modules/security_candidates.py": 800,
            "app/workflow_function_modules/security_report.py": 700,
        }
        for file_name, max_lines in limits.items():
            with self.subTest(file=file_name):
                line_count = len(Path(file_name).read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(line_count, max_lines, f"{file_name} should stay split into focused modules")


if __name__ == "__main__":
    unittest.main()
