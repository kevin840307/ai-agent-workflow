You are generating focused automated tests after production Build.

Create focused automated tests for the completed production build.

Critical execution contract:
- Use Qwen/OpenCode built-in file edit/write tools to create or update test files directly.
- If the CLI environment does not expose file edit/write tools, output complete test file blocks using `FILE: tests/test_name.py`, `CONTENT:`, and `END_FILE`.
- The platform will inspect the project diff after you finish or safely materialize explicit FILE blocks when direct tools are unavailable.
- Generated test files must stay inside `tests/` under the selected Project Path.
- Do not edit production files in this step.
- Do not edit `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.

Project Path: {{project_path}}

Requirement:
{{requirement}}

Todo summary:
{{todo}}

Project profile:
{{project_profile}}

Project index:
{{project_index}}

Architecture summary:
{{architecture}}

Latest retry feedback only:
{{latest_failure_feedback}}

Rules:
- Generate project-specific tests for the final assembled behavior, not one repeated placeholder test per task.
- Do not generate placeholder tests such as `assert False`, "implementation is incomplete", TODO-only tests, or tests that intentionally fail.
- The current Requirement is the source of truth. Do not reuse stale tests from a previous run.
- Keep tests small and targeted; avoid broad snapshot or implementation-detail tests.
- Match the existing project test framework when it is clear from Project Profile / Project Index.
- For Python projects, write pytest tests only under tests/.
- Test files must be named tests/test_*.py or tests/conftest.py.
- Import production code from actual existing module paths in the current project.
- For Python projects, pytest runs with Project Path as cwd. Before importing production modules, ensure `sys.path` includes the project root and every real source root needed by the actual file layout, such as `src/`, `app/`, `production/`, or the parent folder of the package you import.
- If production code is under a nested package path such as `production/project/main.py`, add `production/` to `sys.path` before `from project.main import ...`.
- Do not invent package names. Confirm the import path matches an actual `.py` file or package directory shown in Project Index / current files.
- Every generated Python test file and `conftest.py` must be syntactically valid and import every module it references.
- Do not import placeholder module names like `example` unless the project really contains that module.
- Do not create or modify production files.
- Do not run `git commit`, `git push`, or commands that change repository history or remote state.

Completion response:
- If you used direct edit/write tools successfully, respond with a brief Markdown summary that names the changed test files.
- If direct edit/write tools are unavailable or uncertain, output only complete `FILE/CONTENT/END_FILE` blocks for every created or modified test file.
- A FILE block must use this exact shape:
  `FILE: tests/test_name.py`
  `CONTENT:`
  full file content
  `END_FILE`
