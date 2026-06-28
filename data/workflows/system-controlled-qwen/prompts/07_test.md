You are generating automated tests.

Output only FILE/CONTENT/END_FILE blocks. Do not output JSON. Do not use Markdown fences. Do not create production code in this step.

Project Path: {{project_path}}

Project Overview:
{{project_overview}}

Project Profile:
{{project_profile}}

Architecture:
{{architecture}}

Requirement:
{{requirement}}

Spec:
{{spec}}

Todo:
{{todo}}

Previous Failure Feedback:
{{failure_feedback}}

Rules:
- Generate tests according to Requirement + Spec + Todo.
- The current Requirement is the source of truth. Do not reuse stale tests from a previous run.
- Match the existing project test framework when it is clear from Project Overview.
- For Python projects, write pytest tests only under tests/.
- Test files must be named tests/test_*.py or tests/conftest.py.
- Import production code from actual existing module paths shown in Project Profile / Architecture. Prefer the dominant Source roots by usage. Do not invent `src.*` imports unless `src` is the dominant source root or Architecture explicitly says to use it.
- Keep tests separate from production code.
- Tests must target the current Requirement and Acceptance Criteria, not only behavior that already existed before this run.
- When feasible, write tests that would fail before the requested implementation and pass after it.
- Use test file, import, class, and function names derived from the current Requirement and existing architecture.

Return one or more blocks like:

FILE: tests/test_example.py
CONTENT:
from src.example import example


def test_example_behavior():
    assert example()
END_FILE
