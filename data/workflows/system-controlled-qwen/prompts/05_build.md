You are implementing production code in the selected Project Path.

Output only FILE/CONTENT/END_FILE blocks. Do not output JSON. Do not use Markdown fences. Do not create tests in this step.

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

Test Plan:
{{test_plan}}

Test Result / Failure Feedback:
{{test_result}}

{{failure_feedback}}

Rules:
- Implement according to Requirement + Spec + Todo + Test Plan. Do not invent a different product or language.
- The current Requirement is the source of truth. Do not reuse stale output from a previous run.
- Match the existing project language, framework, file naming, and folder structure from Project Overview / Architecture.
- If the project already has files, modify/create files in the same language as the existing project.
- If Project Profile lists existing source files, choose target production files that fit the dominant Source roots by usage. Do not create a new `src/` directory unless `src` is the dominant source root or Architecture explicitly says to use it.
- Do not switch languages unless the Requirement or Spec explicitly asks for a language migration.
- Create or modify production files only.
- Do not write files under tests/.
- If the project is empty, create a minimal structure that matches the requested language or the language implied by the requirement.
- If the requirement asks to add a new capability, create or modify production files that clearly implement that capability; do not make unrelated edits that only satisfy existing tests.
- Use clear file, class, and function names derived from the current Requirement and existing architecture.
- Keep code small and readable.

Return one or more blocks like:

FILE: src/example.py
CONTENT:
def example():
    ...
END_FILE
