You are generating automated tests.

Output only FILE/CONTENT/END_FILE blocks. Do not output JSON. Do not use Markdown fences. Do not create production code in this step.

Project Path: {{project_path}}

Project Overview:
{{project_overview}}

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
- Match the existing project test framework when it is clear from Project Overview.
- For Python projects, write pytest tests only under tests/.
- Test files must be named tests/test_*.py or tests/conftest.py.
- Keep tests separate from production code.
- For a Python bubble sort requirement, import `bubble_sort` from the production module and test sorted output, duplicates, empty list, and that the original input is not unexpectedly corrupted unless the spec requires in-place sorting.

Return one or more blocks like:

FILE: tests/test_bubble_sort.py
CONTENT:
from bubble_sort import bubble_sort


def test_bubble_sort_orders_numbers():
    assert bubble_sort([3, 1, 2]) == [1, 2, 3]
END_FILE
