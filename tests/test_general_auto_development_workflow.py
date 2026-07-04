from __future__ import annotations

import asyncio
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
from app.workflow_runtime.functions import WorkflowFunctionService


async def _noop_log(_run: dict, _message: str) -> None:
    return None


async def _noop_refresh(_run_id: str) -> None:
    return None


class GeneralAutoDevelopmentWorkflowTests(unittest.TestCase):
    def _wait_for_terminal_run(self, client: TestClient, run: dict, timeout_sec: float = 12) -> dict:
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

    def test_workflow_loads_with_optional_external_validation_retrying_build_when_needed(self) -> None:
        workflow = workflow_asset_service.load_workflow_asset("general-auto-development")

        keys = [step["key"] for step in workflow["steps"]]
        self.assertLessEqual(len(keys), 16)
        self.assertEqual(
            keys,
            [
                "prepare_project",
                "plan_tasks",
                "implementation_review",
                "build",
                "generate_tests",
                "run_test",
                "run_external_validation",
                "final_review",
                "diff_review",
                "final_gate",
            ],
        )

        generate_tests = next(step for step in workflow["steps"] if step["key"] == "generate_tests")
        self.assertEqual(generate_tests["type"], "ai")
        self.assertEqual(generate_tests["outputFile"], "test-plan.md")
        self.assertEqual(generate_tests["expectedFiles"], ["test-plan.md"])
        self.assertEqual(generate_tests["retryFromStepKey"], "generate_tests")

        build = next(step for step in workflow["steps"] if step["key"] == "build")
        self.assertEqual(build["type"], "ai")
        self.assertGreaterEqual(build["maxRetries"], 10)

        implementation_review = next(step for step in workflow["steps"] if step["key"] == "implementation_review")
        self.assertEqual(implementation_review["type"], "python")

        run_test = next(step for step in workflow["steps"] if step["key"] == "run_test")
        self.assertEqual(run_test["type"], "python")
        self.assertEqual(run_test["function"], "run_pytest")
        self.assertEqual(run_test["retryFromStepKey"], "build")
        self.assertEqual(run_test["failAction"], "selected_step")

        validation = next(step for step in workflow["steps"] if step["key"] == "run_external_validation")
        self.assertEqual(validation["type"], "python")
        self.assertEqual(validation["function"], "run_external_validation")
        self.assertEqual(validation["retryFromStepKey"], "build")
        self.assertEqual(validation["failAction"], "selected_step")
        self.assertTrue(validation["requiresValidationScript"])
        self.assertGreaterEqual(validation["maxRetries"], 10)

        diff_review = next(step for step in workflow["steps"] if step["key"] == "diff_review")
        self.assertEqual(diff_review["type"], "ai")
        self.assertEqual(diff_review["outputFile"], "diff-review.md")
        self.assertEqual(diff_review["retryFromStepKey"], "diff_review")

    def test_general_auto_development_builds_then_generates_tests_before_external_validation(self) -> None:
        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "preparing a project" in lower:
                return """FILE: architecture.md
CONTENT:
# Architecture

## Project Summary
- Current purpose: small Python utility.
- User request: add calculator addition.

## Runtime Agent Settings
- Qwen project settings: missing at `.qwen/settings.json`
- OpenCode project settings: missing at `opencode.json`
- Rule: agent read access may use project settings, but generated edits must remain inside the selected Project path.

## Detected Stack
- Dominant source extensions: .py (1)
- Framework/runtime: Python
- Test framework: pytest
- Package/build command: python -m pytest

## Current Structure
- Source layout: project root modules
- Test layout: tests/
- Important config files: validation.py

## Implementation Rules
- Follow the existing language and structure.
- Keep production code and tests separate.
- Do not edit files outside the selected Project path.
- Do not skip the external validation script.
END_FILE
"""
            if "create a practical implementation task plan" in lower:
                return """# Todo

Status: READY

## Requirement
- Add an add function.

## Task Index
| ID | Task | Acceptance Criteria |
| --- | --- | --- |
| TASK-001 | Implement add | AC-001 |

## Tasks

### TASK-001: Implement add
- Goal: provide calculator.add(a, b)
- Files: calculator.py, tests/test_calculator.py
- Acceptance Criteria:
  - AC-001: add(2, 3) returns 5.
- Validation:
  - Covered by generated automated tests and validation.py.

## External Validation
- validation.py is mandatory.
- The workflow must run automated tests before external validation.

## Suggested Todo Files
- None.
"""
            if "review the task plan before implementation" in lower:
                return """# Implementation Review

Status: PASS
Confidence: 0.95

## Checks
- Plan is concrete.

## Findings
- None.
"""
            if "generating focused automated tests" in lower:
                return """FILE: tests/test_calculator.py
CONTENT:
from calculator import add


def test_add_returns_sum():
    assert add(2, 3) == 5
END_FILE
"""
            if "implement the approved task plan" in lower:
                return """FILE: calculator.py
CONTENT:
def add(a, b):
    return a + b
END_FILE
"""
            if "perform the final workflow review" in lower:
                return """# Final Review

Status: PASS
Confidence: 0.98

## Summary
- Implemented add and verified with tests plus validation.py.

## Verification
- Automated test result: PASS
- External validation script result: PASS
- Requirement coverage: PASS
- Architecture alignment: PASS
- Files stayed inside Project path: PASS

## Remaining Risks
- None.
"""
            return "Status: PASS\n"

        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
            ):
                project = Path(tmp) / "project"
                project.mkdir()
                (project / "validation.py").write_text(
                    "from calculator import add\n"
                    "assert add(10, 5) == 15\n"
                    "print('external validation ok')\n",
                    encoding="utf-8",
                )
                with TestClient(app) as client:
                    session_response = client.post(
                        "/api/sessions",
                        json={"title": "General Auto Dev E2E", "project_path": str(project)},
                    )
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": "general-auto-development",
                            "requirement": "Add a Python add function.",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = self._wait_for_terminal_run(client, run_response.json())

                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertTrue((project / "tests" / "test_calculator.py").exists())
                    self.assertTrue((project / "calculator.py").exists())
                    step_keys = [step["key"] for step in run["steps"]]
                    self.assertLess(step_keys.index("build"), step_keys.index("generate_tests"))
                    self.assertLess(step_keys.index("generate_tests"), step_keys.index("run_test"))
                    self.assertLess(step_keys.index("run_test"), step_keys.index("run_external_validation"))
                    self.assertIn("external validation ok", (Path(run["workspace"]) / "output" / "external-validation-result.md").read_text(encoding="utf-8"))
                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve

    def test_general_auto_development_can_complete_bubble_sort_from_prompt_only(self) -> None:
        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "preparing a project" in lower:
                return """FILE: architecture.md
CONTENT:
# Architecture

## Project Summary
- Current purpose: empty Python utility project.
- User request: implement bubble sort.

## Runtime Agent Settings
- Qwen project settings: missing at `.qwen/settings.json`
- OpenCode project settings: missing at `opencode.json`
- Rule: agent read access may use project settings, but generated edits must remain inside the selected Project path.

## Detected Stack
- Dominant source extensions: .py (1)
- Framework/runtime: Python
- Test framework: pytest
- Package/build command: python -m pytest

## Current Structure
- Source layout: project root modules
- Test layout: tests/
- Important config files: validation.py

## Implementation Rules
- Follow the existing language and structure.
- Keep production code and tests separate.
- Do not edit files outside the selected Project path.
- Do not skip the external validation script.
END_FILE
"""
            if "create a practical implementation task plan" in lower:
                return """# Todo

Status: READY

## Requirement
- Implement a Python bubble sort function.

## Task Index
| ID | Task | Acceptance Criteria |
| --- | --- | --- |
| TASK-001 | Implement bubble sort | AC-001 |

## Tasks

### TASK-001: Implement bubble sort
- Goal: provide bubble_sort(values) in bubble_sort.py.
- Files: bubble_sort.py and tests/test_bubble_sort.py.
- Acceptance Criteria:
  - AC-001: bubble_sort returns a sorted list for normal, duplicate, negative, empty, and single-item inputs.
- Validation:
  - Covered by generated automated tests and validation.py.

## Execution SOP
- Step 1: Build production code only.
- Step 2: Generate tests only.
- Step 3: Run automated tests.
- Step 4: Run mandatory external validation.

## External Validation
- validation.py is mandatory.
- The workflow must retry Build when validation fails.

## Suggested Todo Files
- None.
"""
            if "generating focused automated tests" in lower:
                return """FILE: tests/test_bubble_sort.py
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
            if "implement the approved task plan" in lower:
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
"""
            return "Status: PASS\n"

        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
            ):
                project = Path(tmp) / "bubble-project"
                project.mkdir()
                (project / "validation.py").write_text(
                    "from bubble_sort import bubble_sort\n"
                    "assert bubble_sort([9, 2, 5, 2, -3]) == [-3, 2, 2, 5, 9]\n"
                    "assert bubble_sort(('b', 'a', 'c')) == ['a', 'b', 'c']\n"
                    "print('bubble sort validation ok')\n",
                    encoding="utf-8",
                )
                with TestClient(app) as client:
                    session_response = client.post(
                        "/api/sessions",
                        json={"title": "Bubble Sort E2E", "project_path": str(project)},
                    )
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": "general-auto-development",
                            "requirement": "Use Python to implement a bubble sort function.",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = self._wait_for_terminal_run(client, run_response.json())

                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertEqual((project / "bubble_sort.py").read_text(encoding="utf-8").count("def bubble_sort"), 1)
                    self.assertTrue((project / "tests" / "test_bubble_sort.py").exists())
                    self.assertFalse((project.parent / "bubble_sort.py").exists())
                    step_keys = [step["key"] for step in run["steps"]]
                    self.assertLess(step_keys.index("build"), step_keys.index("generate_tests"))
                    self.assertLess(step_keys.index("generate_tests"), step_keys.index("run_test"))
                    self.assertLess(step_keys.index("run_test"), step_keys.index("run_external_validation"))
                    output_dir = Path(run["workspace"]) / "output"
                    self.assertIn("ExitCode: 0", (output_dir / "test-result.md").read_text(encoding="utf-8"))
                    self.assertIn("bubble sort validation ok", (output_dir / "external-validation-result.md").read_text(encoding="utf-8"))
                    self.assertIn("Status: PASS", (output_dir / "final-review.md").read_text(encoding="utf-8"))
                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve

    def test_general_auto_development_can_complete_yaml_crud_from_prompt_only(self) -> None:
        expected_yaml = """users:
  - id: alice
    role: reader
    enabled: true
  - id: bob
    role: admin
    enabled: true
  - id: carol
    role: reader
    enabled: true
"""

        def qwen_response(prompt: str) -> str:
            lower = prompt.lower()
            if "preparing a project" in lower:
                return """FILE: architecture.md
CONTENT:
# Architecture

## Project Summary
- Current purpose: YAML config transformation project.
- User request: apply CRUD operations from config/crud.yaml to config/users.yaml and write generated/users.yaml.

## Runtime Agent Settings
- Qwen project settings: missing at `.qwen/settings.json`
- OpenCode project settings: missing at `opencode.json`
- Rule: agent read access may use project settings, but generated edits must remain inside the selected Project path.

## Detected Stack
- Primary language: YAML + Python validation
- Framework/runtime: Python
- Test framework: pytest
- Package/build command: python -m pytest

## Current Structure
- Source layout: config/users.yaml and config/crud.yaml
- Test layout: tests/
- Important config files: validation.py

## Implementation Rules
- Read config/users.yaml as the before state.
- Read config/crud.yaml as the CRUD instruction source.
- Write generated/users.yaml only.
- Keep production code and tests separate.
- Do not edit files outside the selected Project path.
- Do not skip the external validation script.
END_FILE
"""
            if "create a practical implementation task plan" in lower:
                return """# Todo

Status: READY

## Requirement
- Apply YAML CRUD operations from config/crud.yaml to config/users.yaml and write generated/users.yaml.

## Task Index
| ID | Task | Acceptance Criteria |
| --- | --- | --- |
| TASK-001 | Generate CRUD output YAML | AC-001 |

## Tasks

### TASK-001: Generate CRUD output YAML
- Goal: produce generated/users.yaml from config/users.yaml plus config/crud.yaml.
- Files: generated/users.yaml and tests/test_yaml_crud.py.
- Acceptance Criteria:
  - AC-001: generated/users.yaml keeps alice, updates bob, creates carol, and deletes legacy.
- Validation:
  - Covered by generated automated tests and validation.py.

## Execution SOP
- Step 1: Build generated/users.yaml only.
- Step 2: Generate tests only.
- Step 3: Run automated tests.
- Step 4: Run mandatory external validation.

## External Validation
- validation.py is mandatory.
- The workflow must retry Build when validation fails.

## Suggested Todo Files
- None.
"""
            if "generating focused automated tests" in lower:
                return f"""FILE: tests/test_yaml_crud.py
CONTENT:
from pathlib import Path


EXPECTED = {expected_yaml!r}


def test_generated_yaml_matches_crud_config():
    assert Path("config/users.yaml").exists()
    assert Path("config/crud.yaml").exists()
    actual = Path("generated/users.yaml").read_text(encoding="utf-8")
    assert actual == EXPECTED
    before = Path("config/users.yaml").read_text(encoding="utf-8")
    assert "id: legacy" in before
    assert "id: legacy" not in actual
    assert "role: admin" in actual
    assert "id: carol" in actual
END_FILE
"""
            if "implement the approved task plan" in lower:
                return f"""FILE: generated/users.yaml
CONTENT:
{expected_yaml}END_FILE
"""
            return "Status: PASS\n"

        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_USE_SERVE"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp, patch(
                "app.runtime_modules.qwen.mock_qwen_response", side_effect=qwen_response
            ):
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
                (project / "validation.py").write_text(
                    "from pathlib import Path\n\n"
                    "before = Path('config/users.yaml').read_text(encoding='utf-8')\n"
                    "after_path = Path('generated/users.yaml')\n"
                    "assert after_path.exists(), 'generated/users.yaml was not created'\n"
                    "after = after_path.read_text(encoding='utf-8')\n"
                    f"expected = {expected_yaml!r}\n"
                    "assert after == expected, 'generated YAML does not match expected CRUD result'\n"
                    "assert 'id: legacy' in before and 'id: legacy' not in after\n"
                    "assert 'id: bob' in before and 'role: writer' in before\n"
                    "assert 'id: bob' in after and 'role: admin' in after\n"
                    "assert 'id: carol' not in before and 'id: carol' in after\n"
                    "print('yaml crud validation ok')\n",
                    encoding="utf-8",
                )

                with TestClient(app) as client:
                    session_response = client.post(
                        "/api/sessions",
                        json={"title": "YAML CRUD E2E", "project_path": str(project)},
                    )
                    self.assertEqual(session_response.status_code, 200, session_response.text)
                    session = session_response.json()
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": "general-auto-development",
                            "requirement": "Apply CRUD operations from config/crud.yaml to config/users.yaml and write generated/users.yaml.",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = self._wait_for_terminal_run(client, run_response.json())

                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertEqual((project / "generated" / "users.yaml").read_text(encoding="utf-8"), expected_yaml)
                    self.assertIn("role: writer", (project / "config" / "users.yaml").read_text(encoding="utf-8"))
                    self.assertTrue((project / "tests" / "test_yaml_crud.py").exists())
                    self.assertFalse((project.parent / "generated" / "users.yaml").exists())
                    output_dir = Path(run["workspace"]) / "output"
                    self.assertIn("ExitCode: 0", (output_dir / "test-result.md").read_text(encoding="utf-8"))
                    self.assertIn("yaml crud validation ok", (output_dir / "external-validation-result.md").read_text(encoding="utf-8"))
                    self.assertIn("Status: PASS", (output_dir / "final-review.md").read_text(encoding="utf-8"))
                    client.delete(f"/api/sessions/{session['id']}")
        finally:
            if old_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = old_mock
            if old_use_serve is None:
                os.environ.pop("QWEN_USE_SERVE", None)
            else:
                os.environ["QWEN_USE_SERVE"] = old_use_serve

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
            run = {
                "id": "run-required",
                "workspace": str(workspace),
                "project_path": str(project),
                "_current_step_config": {"requiresValidationScript": True},
            }

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
            (project / "validation.py").write_text(
                "from pathlib import Path\n"
                "Path('validated.txt').write_text('ok', encoding='utf-8')\n"
                "print('validation ok')\n",
                encoding="utf-8",
            )

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
            (project / "tools" / "check_config.py").write_text(
                "from pathlib import Path\n"
                "Path('custom-validation.txt').write_text('ok', encoding='utf-8')\n"
                "print('custom validation ok')\n",
                encoding="utf-8",
            )

            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {
                "id": "run-3",
                "workspace": str(workspace),
                "project_path": str(project),
                "validation_script": "tools/check_config.py",
            }
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
            run = {
                "id": "run-4",
                "workspace": str(workspace),
                "project_path": str(project),
                "validation_script": str(external),
            }
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("absolute validation ok", result)


if __name__ == "__main__":
    unittest.main()
