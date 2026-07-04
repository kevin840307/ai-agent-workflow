You are generating focused automated tests after production Build.

Create focused automated tests for the completed production build.

Critical execution contract:
- Use Qwen/OpenCode built-in file edit/write tools to create or update test files directly.
- Do not return test source code for the platform to materialize.
- Do not output full file contents.
- The platform will only inspect the project diff after you finish.
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
- The current Requirement is the source of truth. Do not reuse stale tests from a previous run.
- Keep tests small and targeted; avoid broad snapshot or implementation-detail tests.
- Match the existing project test framework when it is clear from Project Profile / Project Index.
- For Python projects, write pytest tests only under tests/.
- Test files must be named tests/test_*.py or tests/conftest.py.
- Import production code from actual existing module paths in the current project.
- For Python projects that place modules under `src/` without package installation, add the project root and `src/` directory to `sys.path` before importing production modules.
- Do not import placeholder module names like `example` unless the project really contains that module.
- Do not create or modify production files.
- Do not run `git commit`, `git push`, or commands that change repository history or remote state.

Completion response:
- After editing test files directly, respond with a brief Markdown summary only.
- Do not include full file contents.
