Implement the approved task plan.

Requirement:
{{requirement}}

Architecture:
{{architecture}}

Todo:
{{todo}}

Generated tests:
{{test_plan}}

Latest test result:
{{test_result}}

Implementation review:
{{step_output}}

Project profile:
{{project_profile}}

Failure feedback from previous retries:
{{failure_feedback}}

Rules:
- Output production code FILE/CONTENT/END_FILE blocks only.
- Do not output explanations outside FILE blocks.
- Do not create or modify test files in this Build step.
- Keep generated edits inside Project path only.
- Follow the existing architecture, language, source layout, naming style, and dependency style.
- If the project has `.qwen/settings.json` or `opencode.json`, treat them as project-local agent settings only.
- Fix every concrete validation failure mentioned in the failure feedback.
- If tests already exist from Generate Tests, implement production code that satisfies those tests without editing test files.
- Follow the Todo task order: implement TASK-001, then TASK-002, and continue one task at a time mentally before producing the final changed production files.
- Do not mark the workflow complete; the mandatory external validation step will decide pass/fail.

Path rules:
- FILE paths must be relative to Project path.
- Do not use absolute paths.
- Do not use `..`.
- Do not write into `.ai-workflow`.

Output format:

FILE: relative/path.ext
CONTENT:
...
END_FILE
