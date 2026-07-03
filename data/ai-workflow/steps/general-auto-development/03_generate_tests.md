You are generating focused automated tests after production Build.

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

Todo:
{{todo}}

Build result:
{{build_result}}

Failure feedback from previous retries:
{{failure_feedback}}

Rules:
- Generate tests that prove the current Requirement and Todo acceptance criteria.
- User instructions and provided config files are the source of truth. Tests must assert the explicit behavior, file paths, and output format the user requested.
- If the user restricts allowed test tools, libraries, commands, languages, or frameworks, obey that restriction exactly.
- The current Requirement is the source of truth. Do not reuse stale tests from a previous run.
- Keep tests small and targeted; avoid broad snapshot or implementation-detail tests.
- Match the existing project test framework when it is clear from Project Overview / Project Profile.
- For Python projects, write pytest tests only under tests/.
- Test files must be named tests/test_*.py or tests/conftest.py.
- Import production code from actual existing module paths shown in Project Profile / Architecture / Build result.
- For YAML/JSON/config CRUD tasks, tests should verify the generated output file exists and matches the requested CRUD operations without modifying production or data files.
- Keep tests separate from production code.
- Do not create or modify production files.
- You may use read-only context from outside Project path, but generated test files must stay inside this Project path.

Return one or more blocks like:

FILE: tests/test_example.py
CONTENT:
from example import example


def test_example_behavior():
    assert example()
END_FILE
