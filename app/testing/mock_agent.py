from __future__ import annotations

import os
from collections import defaultdict


_SCENARIO_COUNTS: dict[str, int] = defaultdict(int)


def _scenario_once(key: str) -> bool:
    _SCENARIO_COUNTS[key] += 1
    return _SCENARIO_COUNTS[key] == 1


def mock_qwen_response(prompt: str) -> str:
    """Deterministic Qwen-like output for local UI and workflow E2E tests.

    QWEN_MOCK_SCENARIO can intentionally bend one mock response so manual UI
    tests can exercise failed review, retry, and validation surfaces without
    depending on a real model behaving badly.
    """
    normalized = prompt.lower()
    scenario = os.environ.get("QWEN_MOCK_SCENARIO", "").strip().lower()

    if "# compact reuse retry" in normalized and "step: generate_task_prompts" in normalized:
        import json
        return json.dumps(
            {
                "goal": "Implement a deterministic mock Python feature with tests",
                "spec": "# SPEC\n\n## Goal\nImplement the requested deterministic Python helper.\n\n## Acceptance Criteria\n- AC-001: workflow_greeting exists and is import-safe.\n- AC-002: workflow_greeting returns hello from controlled workflow.\n- AC-003: tests exist and pass.\n\n## Test Expectations\n- Include a focused automated test.\n\n## Review Checklist\n- Production code exists.\n- Tests exist or validation passes.",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "Repair and complete feature with tests",
                        "kind": "repair",
                        "prompt": "Repair the project so workflow_greeting and its focused tests satisfy the SPEC. Directly edit project files and keep the code import-safe.",
                        "acceptance": ["Helper exists", "Tests pass", "Validation passes"],
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    if "# compact reuse retry" in normalized and "step: build" in normalized:
        return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "# compact reuse retry" in normalized and "step: auto_generation" in normalized:
        return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "you are planning a fixed sop development run for a cli coding agent" in normalized:
        import json
        return json.dumps(
            {
                "goal": "Implement a deterministic mock Python feature with tests",
                "spec": "# SPEC\n\n## Goal\nImplement the requested deterministic Python helper.\n\n## Acceptance Criteria\n- AC-001: workflow_greeting exists and is import-safe.\n- AC-002: workflow_greeting returns hello from controlled workflow.\n- AC-003: tests or validation verify the behavior.\n\n## Test Expectations\n- Include a focused automated test unless validation is the only requested verifier.\n\n## Review Checklist\n- Production code exists.\n- Tests exist or validation passes.\n- No workflow files are modified.",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "Implement feature and tests",
                        "kind": "implementation",
                        "prompt": "Create the requested Python helper and focused tests inside the project. Directly edit real project files and keep the code import-safe.",
                        "acceptance": ["Production helper exists", "Tests verify the helper or validation passes", "Project remains import-safe"],
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    if "you are planning the next prompts for a cli coding agent" in normalized or "you are the human-style planner for a cli agent session" in normalized:
        import json
        return json.dumps(
            {
                "goal": "Implement a deterministic mock Python feature with tests",
                "spec": "# SPEC\n\n## Goal\nImplement the requested deterministic Python helper.\n\n## Scope\n- Add a production helper named workflow_greeting.\n- Add automated tests that verify the helper behavior.\n\n## Acceptance Criteria\n- AC-001: workflow_greeting exists and is import-safe.\n- AC-002: workflow_greeting returns hello from controlled workflow.\n- AC-003: tests exist and pass.\n\n## Test Expectations\n- Include a focused automated test for workflow_greeting.\n\n## Review Checklist\n- Production code exists.\n- Tests exist or validation passes.\n- No workflow files are modified.",
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "Implement feature and tests",
                        "kind": "implementation",
                        "prompt": "Create the requested Python helper and focused tests inside the project. Directly edit real project files and keep the code import-safe.",
                        "acceptance": ["Production helper exists", "Tests verify the helper", "Project tests pass"],
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n"

    if "continue the same cli coding session and complete this sop task" in normalized:
        if scenario == "general_no_files_once" and _scenario_once("general_no_files_once:build"):
            return "Status: DONE\n\nIntentional mock output without project edits for general retry coverage.\n"
        if scenario == "general_validation_fail_once" and _scenario_once("general_validation_fail_once:build"):
            return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "wrong greeting"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""
        return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "continue the same cli coding session and execute the current ai-generated prompt" in normalized or "continue the cli coding session and complete this task" in normalized:
        if scenario == "adaptive_no_files_once" and _scenario_once("adaptive_no_files_once:auto_generation"):
            return "Status: DONE\n\nIntentional mock output without project edits for adaptive retry coverage.\n"
        if scenario == "adaptive_validation_fail_once" and _scenario_once("adaptive_validation_fail_once:auto_generation"):
            return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "wrong greeting"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""
        return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "review the completed sop development result against the spec" in normalized:
        if scenario == "general_review_fail_once" and _scenario_once("general_review_fail_once:implementation_review"):
            return "# Implementation Review\n\nStatus: FAIL\nConfidence: 1.0\n\n## Findings\n- Intentional mock implementation review failure.\n\n## Test Check\n- Tests must be checked on retry.\n\n## Required Fixes\n- Re-run Execute Task Loop and ensure workflow_greeting plus tests satisfy the SPEC.\n"
        return "# Implementation Review\n\nStatus: PASS\nConfidence: 1.0\n\n## Findings\n- Project files satisfy the SPEC and mock validation is expected to pass or be skipped.\n\n## Test Check\n- Tests are present or validation is available.\n\n## Required Fixes\n- None\n"

    if "review and validate the completed project change against the spec" in normalized or "review the completed project change" in normalized:
        if scenario == "adaptive_review_fail_once" and _scenario_once("adaptive_review_fail_once:ai_review"):
            return "# AI Review\n\nStatus: FAIL\nConfidence: 1.0\n\n## Findings\n- Intentional mock review failure.\n\n## Test Check\n- Tests must be checked on retry.\n\n## Required Fixes\n- Re-run Execute Prompts and ensure workflow_greeting plus tests satisfy the SPEC.\n"
        return "# AI Review\n\nStatus: PASS\nConfidence: 1.0\n\n## Findings\n- Project files satisfy the SPEC and mock validation is expected to pass.\n\n## Test Check\n- Tests are present or validation is available.\n\n## Required Fixes\n- None\n"

    if "create a concise task plan for this project request" in normalized:
        return """# Todo

Status: READY

## Task Index
| ID | Task | Acceptance Criteria | Depends On |
| --- | --- | --- | --- |
| TASK-001 | Create the production mock helper | Helper exists and is import-safe | None |

## Notes
- Testing / validation expectation: Add focused tests after build and run them.
- Assumptions: Python standard library is enough.
"""

    if "review the task plan" in normalized:
        return "# Implementation Review\n\nStatus: PASS\nConfidence: 1.0\n\n## Findings\n- Plan is scoped and actionable.\n\n## Required Fixes\n- None\n"

    if "continue the cli coding session and implement the current build task" in normalized:
        return """Status: READY

FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE
"""

    if "continue the cli coding session and add focused automated tests" in normalized:
        return """Status: READY

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "review the final project result" in normalized:
        return "# Final Review\n\nStatus: PASS\nConfidence: 1.0\n\n## Findings\n- Implementation, tests, and validation satisfy the mock request.\n\n## Required Fixes\n- None\n"

    if scenario == "fail_final_review_once" and ("output/final-review.md" in prompt or "you are doing the final workflow review" in normalized):
        if _scenario_once("fail_final_review_once:final_review"):
            return "Status: FAIL\n\n## Findings\n- Intentional mock failure for Playwright retry coverage.\nConfidence: 1.0\n"

    if scenario == "generate_tests_no_files" and ("you are generating automated tests" in normalized or "OUTPUT_FILE: output/test-plan.md" in prompt):
        return "Status: DONE\n\n## Test Plan\n- Intentional mock output without FILE blocks for Playwright gate failure coverage.\n"

    if scenario == "build_no_files" and ("you are implementing production code" in normalized or "OUTPUT_FILE: output/build-result.md" in prompt):
        return "Status: DONE\n\nIntentional mock build output without FILE blocks.\n"

    if "you are preparing project architecture context" in normalized or "only create or update `architecture.md`" in prompt:
        return """Status: DONE

FILE: architecture.md
CONTENT:
# Architecture

## Overview
Mock workflow project used for deterministic end-to-end verification.

## Project Structure
- Production Python modules live at the project root.
- Tests live under tests/.

## Runtime And Entry Points
- Python standard library modules are imported directly by tests.

## Data Flow
- Tests call production helper functions and assert deterministic return values.

## Testing Strategy
- Use Python unittest-compatible test files under tests/.

## Conventions
- Keep production files separate from generated tests.
- Do not write under .ai-workflow or .qwen-workflow.

## Unknowns
- None blocking for mock mode.

## Update Notes
- Generated by mock Qwen for system workflow E2E coverage.
END_FILE
"""

    if "you are producing a reasoning artifact" in normalized and "output/reasoning.md" in prompt:
        return """Status: DONE

## Requirement Understanding
- The workflow should implement a small deterministic Python helper and verify it through generated tests.

## Existing Project Evidence
- Mock mode uses the selected Project Path and existing Python-compatible layout.

## Implementation Direction
- Add a root-level production module with a simple helper function.

## Files Likely To Change
- Production files: workflow_mock_feature.py
- Test files: tests/test_workflow_mock_feature.py

## Constraints
- Keep production code and tests in separate workflow steps.
- Build must not create or modify tests/ files.

## Assumptions
- Python standard library is sufficient.

## Risks
- Build output must include production FILE/CONTENT/END_FILE blocks.
"""

    if "reviewing `output/spec.md`" in normalized or "reviewing `output/todo.md`" in normalized:
        return "Status: PASS\n\n## Findings\n- None.\nConfidence: 1.0\n"

    if "you are generating automated tests" in normalized or "OUTPUT_FILE: output/test-plan.md" in prompt:
        return """Status: DONE

FILE: tests/test_workflow_mock_feature.py
CONTENT:
import unittest

from workflow_mock_feature import workflow_greeting


class WorkflowMockFeatureTests(unittest.TestCase):
    def test_workflow_greeting_is_deterministic(self):
        self.assertEqual(workflow_greeting(), "hello from controlled workflow")


if __name__ == "__main__":
    unittest.main()
END_FILE
"""

    if "you are producing a build reasoning artifact" in normalized and "output/build-reasoning.md" in prompt:
        return """Status: DONE

## Target Production Files
- workflow_mock_feature.py

## Forbidden Files
- tests/
- .ai-workflow/
- .qwen-workflow/

## Implementation Plan
- Add a small production helper function that returns the deterministic greeting expected by tests.

## Acceptance Criteria Mapping
- AC-001 maps to workflow_greeting().
- AC-002 maps to generated tests.
- AC-003 maps to the configured test command.

## Test Awareness
- Generated tests import workflow_mock_feature.workflow_greeting and assert the greeting string.

## Retry Guidance
- None.
"""

    if "you are implementing production code" in normalized or "OUTPUT_FILE: output/build-result.md" in prompt:
        return """FILE: workflow_mock_feature.py
CONTENT:
def workflow_greeting() -> str:
    return "hello from controlled workflow"
END_FILE
"""

    if "output/final-review.md" in prompt or "you are doing the final workflow review" in normalized:
        return "Status: PASS\n\n## Summary\n- Implementation and tests satisfy the spec.\nConfidence: 1.0\n"

    if "you are generating the workflow artifact `output/spec.md`" in normalized or "OUTPUT_FILE: output/spec.md" in prompt:
        return """## Goal
- Build a small Python workflow mock feature that can be implemented and verified by the controlled workflow.

## Scope
- Add a production Python helper for the current requirement.
- Add automated tests through the Generate Tests step.
- Keep workflow artifacts deterministic for mock mode.

## Out of Scope
- Authentication, deployment, external services, and database changes.
- Any unrelated refactor outside the selected project path.

## Input
- User requirement text.
- Existing project files in the selected Project Path.
- Workflow artifacts generated by earlier steps.

## Output
- A production Python module implementing the requested mock behavior.
- Separate automated tests under tests/.
- Passing workflow review and test artifacts.

## Rules
- Production code and tests must be generated by separate workflow steps.
- Build output must create or modify only production files.
- Tests must live under tests/ and target the current requirement.
- Use a small standard-library Python implementation in mock mode.

## Acceptance Criteria
- AC-001: The production helper returns a deterministic greeting for the workflow requirement.
- AC-002: Automated tests verify the helper behavior.
- AC-003: The configured test command exits successfully.

## Unknowns
- None blocking.
"""

    if "you are generating the workflow artifact `output/todo.md`" in normalized or "OUTPUT_FILE: output/todo.md" in prompt:
        return """## Todo List
- TODO-001: Create a production helper that returns a deterministic greeting. (covers AC-001)
- TODO-002: Generate automated tests for the helper behavior. (covers AC-002)
- TODO-003: Run the configured test command and keep it green. (covers AC-003)

## Test Plan
- TEST-001: Verify the helper returns the expected deterministic greeting. (covers AC-001)
- TEST-002: Verify the tests import the production module from the project path. (covers AC-002)
- TEST-003: Verify the configured test command exits successfully. (covers AC-003)

## Done Criteria
- AC-001, AC-002, and AC-003 are implemented and verified.
"""

    return "Status: PASS\n\nReview passed in mock mode.\nConfidence: 1.0\n"
