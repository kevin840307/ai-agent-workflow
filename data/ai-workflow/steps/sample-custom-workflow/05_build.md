You are implementing production code in the selected Project Path.

Output only FILE/CONTENT/END_FILE blocks. Do not output JSON. Do not use Markdown fences. Do not create tests in this step.

Project Path: {{project_path}}

Project Overview:
{{project_overview}}

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
- Match the existing project language, framework, file naming, and folder structure from Project Overview / Architecture.
- If the project already has files, modify/create files in the same language as the existing project.
- Do not switch languages unless the Requirement or Spec explicitly asks for a language migration.
- Create or modify production files only.
- Do not write files under tests/.
- If the project is empty and the requirement asks for Python, create a simple Python module with a clear function name.
- For a bubble sort requirement, provide a reusable `bubble_sort` function.
- Keep code small and readable.

Return one or more blocks like:

FILE: bubble_sort.py
CONTENT:
def bubble_sort(items):
    ...
END_FILE
