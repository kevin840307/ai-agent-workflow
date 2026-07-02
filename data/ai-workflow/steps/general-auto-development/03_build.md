Implement the approved task plan.

Requirement:
{{requirement}}

Architecture:
{{architecture}}

Todo:
{{todo}}

Latest test result:
{{test_result}}

Implementation review:
{{step_output}}

Project profile:
{{project_profile}}

Failure feedback from previous retries:
{{failure_feedback}}

Rules:
- Output Build-owned FILE/CONTENT/END_FILE blocks only: production code, project config, data files, or other requested project artifacts.
- Do not output explanations outside FILE blocks.
- Do not create or modify test files in this Build step.
- Keep generated edits inside Project path only.
- You may use read-only context from outside Project path, but never write outside Project path.
- User instructions and provided config files are the source of truth. Follow explicit user-provided steps, file paths, data formats, and output locations before applying defaults.
- If the user restricts allowed tools, libraries, commands, languages, or frameworks, obey that restriction exactly. Do not introduce a different tool or dependency for convenience.
- Follow the existing architecture, language, source layout, naming style, and dependency style.
- For YAML/JSON/config CRUD tasks, inspect the source file and operation config, then write the requested output file exactly at the requested relative path.
- If the project has `.qwen/settings.json` or `opencode.json`, treat them as project-local agent settings only.
- Fix every concrete validation failure mentioned in the failure feedback.
- Do not wait for generated tests; implement the production code now based on Requirement, Architecture, Todo, and feedback.
- Do not mark the workflow complete; automated tests and mandatory external validation will decide pass/fail.

Path rules:
- FILE paths must be relative to Project path.
- Do not use absolute paths.
- Do not use `..`.
- Do not write into `.ai-workflow`.
- Do not write into `.qwen-workflow`.
- Do not write into `tests/`.
- Do not write files named `test_*.py`.

Output format:

FILE: relative/path.ext
CONTENT:
...
END_FILE
