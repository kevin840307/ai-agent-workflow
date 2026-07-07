from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules import api as runtime
from app.runtime_modules.errors import WorkflowError
from app.services import workflow_asset_service
from app.workflow_runtime.builtin_functions.core import _looks_like_script_argument_error
from app.workflow_runtime.functions import WorkflowFunctionService


async def _noop_log(_run: dict, _message: str) -> None:
    return None


async def _noop_refresh(_run_id: str) -> None:
    return None


class GeneralAutoDevelopmentWorkflowTests(unittest.TestCase):
    def _wait_for_terminal_run(self, client: TestClient, run: dict, timeout_sec: float = 20) -> dict:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            response = client.get(f"/api/workflow-runs/{run['id']}")
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()
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

    def test_workflow_is_fixed_evidence_based_sop_controller(self) -> None:
        workflow = workflow_asset_service.load_workflow_asset("general-auto-development")
        keys = [step["key"] for step in workflow["steps"]]
        self.assertEqual(keys, ["plan_tasks", "build", "generate_tests", "run_test", "implementation_review", "run_external_validation", "final_review", "final_gate"])

        plan = next(step for step in workflow["steps"] if step["key"] == "plan_tasks")
        self.assertEqual(plan["type"], "ai")
        self.assertEqual(plan["expectedFiles"], ["spec.md", "todo.md", "task-manifest.md", "task-manifest.json"])

        build = next(step for step in workflow["steps"] if step["key"] == "build")
        self.assertEqual(build["name"], "Execute Task Loop")
        self.assertTrue(build["enableTaskLoop"])
        self.assertTrue(build["allowTestFilesInTaskLoop"])
        self.assertEqual(build["retryFromStepKey"], "build")
        self.assertEqual(build["retryEscalationEvery"], 3)
        self.assertEqual(build["retryEscalationStepKey"], "plan_tasks")

        generate_tests = next(step for step in workflow["steps"] if step["key"] == "generate_tests")
        self.assertEqual(generate_tests["type"], "ai")
        self.assertEqual(generate_tests["outputFile"], "test-plan.md")

        run_test = next(step for step in workflow["steps"] if step["key"] == "run_test")
        self.assertEqual(run_test["type"], "python")
        self.assertEqual(run_test["function"], "run_pytest")

        review = next(step for step in workflow["steps"] if step["key"] == "implementation_review")
        self.assertEqual(review["type"], "review")
        self.assertEqual(review["outputFile"], "final-review.md")
        self.assertEqual(review["retryFromStepKey"], "build")

        validation = next(step for step in workflow["steps"] if step["key"] == "run_external_validation")
        self.assertEqual(validation["type"], "python")
        self.assertEqual(validation["function"], "run_external_validation")
        self.assertEqual(validation["retryFromStepKey"], "build")
        self.assertFalse(validation["requiresValidationScript"])

        final_review = next(step for step in workflow["steps"] if step["key"] == "final_review")
        self.assertEqual(final_review["type"], "python")
        self.assertEqual(final_review["function"], "validate_general_auto_final")

    def test_validation_script_fallback_does_not_trigger_on_plain_usage_text(self) -> None:
        self.assertFalse(_looks_like_script_argument_error("usage: validator.py [-h] --project PROJECT\nmissing required value"))
        self.assertTrue(_looks_like_script_argument_error("error: unrecognized arguments: --project C:/tmp/project"))

    def _run_general_e2e(self, *, project: Path, requirement: str, qwen_response) -> dict:
        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        old_file_block = os.environ.get("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"
        os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
        try:
            with patch("app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response):
                with TestClient(app) as client:
                    session_response = client.post("/api/sessions", json={"title": "General Auto Dev E2E", "project_path": str(project)})
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={"workflow_id": "general-auto-development", "requirement": requirement},
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = self._wait_for_terminal_run(client, run_response.json())
                    return run
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve
            if old_file_block is None:
                os.environ.pop("QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION", None)
            else:
                os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = old_file_block

    @staticmethod
    def _json_plan(spec: str, prompt: str, title: str = "Implement requested change") -> str:
        return json.dumps(
            {
                "goal": title,
                "spec": spec,
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": title,
                        "kind": "implementation",
                        "prompt": prompt,
                        "acceptance": ["Implementation satisfies the requested behavior", "Tests or validation verify the behavior"],
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        )

    def test_general_auto_development_builds_and_validates_add_function(self) -> None:
        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "fixed sop development run" in lower:
                return self._json_plan(
                    "# SPEC\n\n## Goal\nAdd calculator.add.\n\n## Acceptance Criteria\n- add(2, 3) returns 5.\n- validation.py passes.\n\n## Test Expectations\n- Include a focused pytest test.",
                    "Implement calculator.add(a, b) and add a focused pytest test. Directly edit project files.",
                    "Implement add",
                )
            if "complete this sop task" in lower:
                return """FILE: calculator.py
CONTENT:
def add(a, b):
    return a + b
END_FILE

FILE: tests/test_calculator.py
CONTENT:
from calculator import add


def test_add_returns_sum():
    assert add(2, 3) == 5
END_FILE
"""
            if "completed sop development result" in lower:
                return "# Implementation Review\n\nStatus: PASS\nConfidence: 0.98\n\n## Findings\n- Complete.\n\n## Test Check\n- Tests exist.\n\n## Required Fixes\n- None\n"
            return "Status: PASS\n"

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "validation.py").write_text("from calculator import add\nassert add(10, 5) == 15\nprint('external validation ok')\n", encoding="utf-8")
            run = self._run_general_e2e(project=project, requirement="Add a Python add function.", qwen_response=qwen_response)
            self.assertEqual(run["status"], "done", run.get("error"))
            self.assertTrue((project / "calculator.py").exists())
            self.assertTrue((project / "tests" / "test_calculator.py").exists())
            keys = [step["key"] for step in run["steps"]]
            self.assertEqual(keys, ["plan_tasks", "build", "generate_tests", "run_test", "implementation_review", "run_external_validation", "final_review", "final_gate"])
            self.assertIn("external validation ok", (Path(run["workspace"]) / "output" / "external-validation-result.md").read_text(encoding="utf-8"))

    def test_general_auto_development_can_complete_bubble_sort_from_prompt_only(self) -> None:
        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "fixed sop development run" in lower:
                return self._json_plan(
                    "# SPEC\n\n## Goal\nImplement bubble_sort.\n\n## Acceptance Criteria\n- Handles duplicates, negatives, empty, and single-item inputs.\n- Does not mutate input.\n\n## Test Expectations\n- Include focused tests.",
                    "Implement bubble_sort(values) and add focused tests for normal, duplicate, negative, empty, and single-item inputs. Directly edit project files.",
                    "Implement bubble sort",
                )
            if "complete this sop task" in lower:
                return """FILE: bubble_sort.py
CONTENT:
from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def bubble_sort(values: Iterable[T]) -> list[T]:
    result = list(values)
    n = len(result)
    for end in range(n - 1, 0, -1):
        swapped = False
        for index in range(end):
            if result[index] > result[index + 1]:
                result[index], result[index + 1] = result[index + 1], result[index]
                swapped = True
        if not swapped:
            break
    return result
END_FILE

FILE: tests/test_bubble_sort.py
CONTENT:
from bubble_sort import bubble_sort


def test_bubble_sort_orders_numbers_without_mutating_input():
    values = [5, 1, 4, 2, 8]
    assert bubble_sort(values) == [1, 2, 4, 5, 8]
    assert values == [5, 1, 4, 2, 8]


def test_bubble_sort_handles_duplicates_negatives_and_empty_inputs():
    assert bubble_sort([3, -1, 3, 0]) == [-1, 0, 3, 3]
    assert bubble_sort([]) == []
    assert bubble_sort([7]) == [7]
END_FILE
"""
            if "completed sop development result" in lower:
                return "# Implementation Review\n\nStatus: PASS\nConfidence: 0.98\n\n## Findings\n- Complete.\n\n## Test Check\n- Tests exist.\n\n## Required Fixes\n- None\n"
            return "Status: PASS\n"

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bubble-project"
            project.mkdir()
            (project / "validation.py").write_text(
                "from bubble_sort import bubble_sort\n"
                "assert bubble_sort([9, 2, 5, 2, -3]) == [-3, 2, 2, 5, 9]\n"
                "assert bubble_sort(('b', 'a', 'c')) == ['a', 'b', 'c']\n"
                "print('bubble sort validation ok')\n",
                encoding="utf-8",
            )
            run = self._run_general_e2e(project=project, requirement="Use Python to implement a bubble sort function.", qwen_response=qwen_response)
            self.assertEqual(run["status"], "done", run.get("error"))
            self.assertEqual((project / "bubble_sort.py").read_text(encoding="utf-8").count("def bubble_sort"), 1)
            self.assertTrue((project / "tests" / "test_bubble_sort.py").exists())
            self.assertIn("bubble sort validation ok", (Path(run["workspace"]) / "output" / "external-validation-result.md").read_text(encoding="utf-8"))
            self.assertIn("Status: PASS", (Path(run["workspace"]) / "output" / "final-review.md").read_text(encoding="utf-8"))

    def test_general_auto_development_can_complete_yaml_crud_from_prompt_only(self) -> None:
        expected_yaml = """users:\n  - id: alice\n    role: reader\n    enabled: true\n  - id: bob\n    role: admin\n    enabled: true\n  - id: carol\n    role: reader\n    enabled: true\n"""

        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "fixed sop development run" in lower:
                return self._json_plan(
                    "# SPEC\n\n## Goal\nApply YAML CRUD operations.\n\n## Acceptance Criteria\n- generated/users.yaml keeps alice, updates bob, creates carol, and deletes legacy.\n\n## Test Expectations\n- Include tests or validation for generated YAML.",
                    "Apply CRUD operations from config/crud.yaml to config/users.yaml and write generated/users.yaml plus a focused test. Directly edit project files.",
                    "Generate CRUD output YAML",
                )
            if "complete this sop task" in lower:
                return f"""FILE: generated/users.yaml
CONTENT:
{expected_yaml}END_FILE

FILE: tests/test_yaml_crud.py
CONTENT:
from pathlib import Path


EXPECTED = {expected_yaml!r}


def test_generated_yaml_matches_crud_config():
    actual = Path("generated/users.yaml").read_text(encoding="utf-8")
    assert actual == EXPECTED
END_FILE
"""
            if "completed sop development result" in lower:
                return "# Implementation Review\n\nStatus: PASS\nConfidence: 0.98\n\n## Findings\n- Complete.\n\n## Test Check\n- Tests exist.\n\n## Required Fixes\n- None\n"
            return "Status: PASS\n"

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "yaml-crud-project"
            project.mkdir()
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
            (project / "config" / "crud.yaml").write_text("operations: []\n", encoding="utf-8")
            (project / "validation.py").write_text(
                "from pathlib import Path\n"
                "after_path = Path('generated/users.yaml')\n"
                "assert after_path.exists(), 'generated/users.yaml was not created'\n"
                f"expected = {expected_yaml!r}\n"
                "assert after_path.read_text(encoding='utf-8') == expected\n"
                "print('yaml crud validation ok')\n",
                encoding="utf-8",
            )
            run = self._run_general_e2e(
                project=project,
                requirement="Apply CRUD operations from config/crud.yaml to config/users.yaml and write generated/users.yaml.",
                qwen_response=qwen_response,
            )
            self.assertEqual(run["status"], "done", run.get("error"))
            self.assertEqual((project / "generated" / "users.yaml").read_text(encoding="utf-8"), expected_yaml)
            self.assertTrue((project / "tests" / "test_yaml_crud.py").exists())
            self.assertIn("yaml crud validation ok", (Path(run["workspace"]) / "output" / "external-validation-result.md").read_text(encoding="utf-8"))

    def test_external_validation_skips_when_project_has_no_validation_script_and_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-1", "workspace": str(workspace), "project_path": str(project)}
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))
            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("external validation skipped", result)

    def test_external_validation_fails_when_step_requires_validation_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-required", "workspace": str(workspace), "project_path": str(project), "_current_step_config": {"requiresValidationScript": True}}
            with self.assertRaises(WorkflowError):
                asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))
            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: FAIL", result)
            self.assertIn("No validation script found", result)

    def test_external_validation_runs_project_default_validation_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            (project / "validation.py").write_text("from pathlib import Path\nPath('validated.txt').write_text('ok', encoding='utf-8')\nprint('validation ok')\n", encoding="utf-8")
            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-2", "workspace": str(workspace), "project_path": str(project), "_current_step_config": {"fallbackValidationScripts": ["validation.py"]}}
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))
            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("Script: validation.py", result)
            self.assertIn("validation ok", result)
            self.assertEqual((project / "validated.txt").read_text(encoding="utf-8"), "ok")

    def test_external_validation_uses_run_specific_relative_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            (project / "tools").mkdir()
            (project / "tools" / "check_config.py").write_text("from pathlib import Path\nPath('custom-validation.txt').write_text('ok', encoding='utf-8')\nprint('custom validation ok')\n", encoding="utf-8")
            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-3", "workspace": str(workspace), "project_path": str(project), "validation_script": "tools/check_config.py"}
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))
            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("Script: tools\\check_config.py", result.replace("/", "\\"))
            self.assertEqual((project / "custom-validation.txt").read_text(encoding="utf-8"), "ok")

    def test_external_validation_uses_run_specific_absolute_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            external = Path(tmp) / "provided_validator.py"
            project.mkdir()
            output.mkdir(parents=True)
            external.write_text("print('absolute validation ok')\n", encoding="utf-8")
            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-4", "workspace": str(workspace), "project_path": str(project), "validation_script": str(external)}
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))
            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("absolute validation ok", result)


if __name__ == "__main__":
    unittest.main()
