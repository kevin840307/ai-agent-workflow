from __future__ import annotations

import unittest
from pathlib import Path

from app.services import workflow_asset_service
from app.workflow_runtime.builtin_functions import security_validation
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS


class WorkflowFunctionRefactorContractTests(unittest.TestCase):
    def test_function_catalog_is_filesystem_discovered(self) -> None:
        catalog = workflow_asset_service.function_catalog()
        function_ids = {item["id"] for item in catalog["functions"]}
        expected = {
            "collect_security_context",
            "combine_security_candidates",
            "consensus_agent",
            "generate_security_report",
            "finalize_security_report",
            "require_status_pass",
            "run_pytest",
            "validate_security_candidates",
            "validate_security_report",
            "validate_spec",
            "validate_todo",
        }
        self.assertTrue(expected.issubset(function_ids))

    def test_registry_contains_builtin_callable_contract(self) -> None:
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

    def test_security_validation_facade_stays_focused(self) -> None:
        self.assertTrue(callable(security_validation.validate_security_candidates))
        self.assertTrue(callable(security_validation.combine_security_candidates))
        self.assertTrue(callable(security_validation.validate_security_report))

    def test_builtin_function_files_stay_modular(self) -> None:
        limits = {
            "app/workflow_runtime/builtin_functions/security_validation.py": 120,
            "app/workflow_runtime/builtin_functions/security_common.py": 1100,
            "app/workflow_runtime/builtin_functions/security_candidates.py": 800,
            "app/workflow_runtime/builtin_functions/security_report.py": 700,
        }
        for file_name, max_lines in limits.items():
            with self.subTest(file=file_name):
                line_count = len(Path(file_name).read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(line_count, max_lines, f"{file_name} should stay split into focused modules")


if __name__ == "__main__":
    unittest.main()
