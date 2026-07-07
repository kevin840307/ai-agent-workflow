from __future__ import annotations

import json

SORTING_PROMPT = "幫我用python寫氣泡排序法+選擇排序法+插入排序法+快速排序法+合併排序法+堆積排序法+希爾排序法"
SORT_FUNCTIONS = [
    "bubble_sort",
    "selection_sort",
    "insertion_sort",
    "quick_sort",
    "merge_sort",
    "heap_sort",
    "shell_sort",
]


def is_sorting_self_prompt(prompt: str, scenario: str = "") -> bool:
    lowered = (prompt or "").lower()
    if scenario == "self_prompt_sorting_algorithms":
        return True
    return all(marker in (prompt or "") for marker in ["氣泡排序", "選擇排序", "插入排序", "快速排序", "合併排序", "堆積排序", "希爾排序"])


def _spec() -> str:
    return """# SPEC

## Goal
Implement seven Python sorting algorithms requested by the user prompt: bubble sort, selection sort, insertion sort, quick sort, merge sort, heap sort, and shell sort.

## Scope
- Create a production Python module named `sorting_algorithms.py`.
- Provide these functions: `bubble_sort`, `selection_sort`, `insertion_sort`, `quick_sort`, `merge_sort`, `heap_sort`, and `shell_sort`.
- Each function accepts an iterable of comparable values and returns a newly sorted list.
- Add focused automated tests or validation evidence for all seven functions.

## Out of Scope
- CLI packaging, GUI work, third-party dependencies, database changes, and unrelated project refactors.

## Input
- User prompt: 幫我用python寫氣泡排序法+選擇排序法+插入排序法+快速排序法+合併排序法+堆積排序法+希爾排序法
- Existing project files under the selected Project Path.

## Output
- `sorting_algorithms.py` with all seven sorting functions.
- Test or validation evidence that every sorting function handles normal, duplicate, negative, empty, and single-item input.

## Rules
- Keep implementation in production files, not only tests or workflow artifacts.
- Do not mutate the caller's input iterable.
- Use Python standard library only.
- Keep writes inside the selected Project Path.

## Acceptance Criteria
- AC-001: `sorting_algorithms.py` exists and exports exactly the requested seven sorting functions.
- AC-002: Every sorting function returns the same result as Python `sorted()` for representative numeric and string inputs.
- AC-003: Every sorting function returns a new list and does not mutate the original list.
- AC-004: Validation or tests pass inside the fixture project.

## Unknowns
- None blocking; ascending order is assumed because no descending order was requested.
"""


def _task_prompt() -> str:
    return (
        "Implement `sorting_algorithms.py` with bubble_sort, selection_sort, insertion_sort, "
        "quick_sort, merge_sort, heap_sort, and shell_sort. Each function should return a new "
        "ascending list without mutating input. Also add focused tests covering all seven functions. "
        "Directly edit files inside the project."
    )


def sorting_task_manifest(*, goal: str = "Implement seven Python sorting algorithms") -> str:
    return json.dumps(
        {
            "goal": goal,
            "spec": _spec(),
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Implement seven sorting algorithms with tests",
                    "kind": "implementation",
                    "prompt": _task_prompt(),
                    "acceptance": [
                        "All seven sorting functions exist",
                        "Functions do not mutate caller input",
                        "Tests or validation cover numeric and string inputs",
                    ],
                }
            ],
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def sorting_source() -> str:
    return '''from __future__ import annotations

import heapq
from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def _as_list(values: Iterable[T]) -> list[T]:
    """Return a copied list so sorting functions never mutate caller input."""
    return list(values)


def bubble_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    n = len(result)
    for end in range(n - 1, 0, -1):
        swapped = False
        for index in range(end):
            if result[index] > result[index + 1]:
                result[index], result[index + 1] = result[index + 1], result[index]
                swapped = True
        if not swapped:
            break
    return result


def selection_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    n = len(result)
    for index in range(n):
        min_index = index
        for scan in range(index + 1, n):
            if result[scan] < result[min_index]:
                min_index = scan
        if min_index != index:
            result[index], result[min_index] = result[min_index], result[index]
    return result


def insertion_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    for index in range(1, len(result)):
        current = result[index]
        position = index - 1
        while position >= 0 and result[position] > current:
            result[position + 1] = result[position]
            position -= 1
        result[position + 1] = current
    return result


def quick_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    if len(result) <= 1:
        return result
    pivot = result[len(result) // 2]
    left = [item for item in result if item < pivot]
    middle = [item for item in result if item == pivot]
    right = [item for item in result if item > pivot]
    return quick_sort(left) + middle + quick_sort(right)


def merge_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    if len(result) <= 1:
        return result
    midpoint = len(result) // 2
    left = merge_sort(result[:midpoint])
    right = merge_sort(result[midpoint:])
    merged: list[T] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] <= right[right_index]:
            merged.append(left[left_index])
            left_index += 1
        else:
            merged.append(right[right_index])
            right_index += 1
    merged.extend(left[left_index:])
    merged.extend(right[right_index:])
    return merged


def heap_sort(values: Iterable[T]) -> list[T]:
    heap = _as_list(values)
    heapq.heapify(heap)
    return [heapq.heappop(heap) for _ in range(len(heap))]


def shell_sort(values: Iterable[T]) -> list[T]:
    result = _as_list(values)
    gap = len(result) // 2
    while gap > 0:
        for index in range(gap, len(result)):
            current = result[index]
            position = index
            while position >= gap and result[position - gap] > current:
                result[position] = result[position - gap]
                position -= gap
            result[position] = current
        gap //= 2
    return result
'''


def sorting_tests() -> str:
    return '''from sorting_algorithms import (
    bubble_sort,
    heap_sort,
    insertion_sort,
    merge_sort,
    quick_sort,
    selection_sort,
    shell_sort,
)

SORTERS = [
    bubble_sort,
    selection_sort,
    insertion_sort,
    quick_sort,
    merge_sort,
    heap_sort,
    shell_sort,
]


def test_all_sorters_match_python_sorted_and_do_not_mutate_input():
    cases = [
        [5, 1, 4, 2, 8],
        [3, -1, 3, 0, 2, -1],
        [],
        [7],
        [9, 8, 7, 6, 5],
        ["banana", "apple", "cherry", "apple"],
    ]
    for sorter in SORTERS:
        for values in cases:
            original = list(values)
            result = sorter(values)
            assert result == sorted(original), sorter.__name__
            assert values == original, f"{sorter.__name__} mutated input"
            assert isinstance(result, list)
'''


def sorting_file_blocks() -> str:
    return f"""Status: READY

FILE: sorting_algorithms.py
CONTENT:
{sorting_source()}END_FILE

FILE: tests/test_sorting_algorithms.py
CONTENT:
{sorting_tests()}END_FILE
"""


def sorting_review_json() -> str:
    return json.dumps(
        {
            "status": "PASS",
            "confidence": 1.0,
            "summary": "All seven requested sorting algorithms are implemented in production code and covered by validation/test evidence.",
            "missing_items": [],
            "test_check": "validation.py and generated tests cover all seven functions, duplicates, negatives, empty input, single input, strings, and mutation safety.",
            "repair_prompt": "",
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def validation_script() -> str:
    function_list = repr(SORT_FUNCTIONS)
    return f'''from sorting_algorithms import {", ".join(SORT_FUNCTIONS)}

SORT_FUNCTIONS = {function_list}
SORTERS = [{", ".join(SORT_FUNCTIONS)}]
CASES = [
    [5, 1, 4, 2, 8],
    [3, -1, 3, 0, 2, -1],
    [],
    [7],
    [9, 8, 7, 6, 5],
    ["banana", "apple", "cherry", "apple"],
]

for sorter in SORTERS:
    assert sorter.__name__ in SORT_FUNCTIONS
    for values in CASES:
        original = list(values)
        result = sorter(values)
        assert result == sorted(original), f"{{sorter.__name__}} failed for {{values!r}}"
        assert values == original, f"{{sorter.__name__}} mutated input"
        assert isinstance(result, list), f"{{sorter.__name__}} did not return list"

print("self-prompt sorting validation ok: " + ", ".join(SORT_FUNCTIONS))
'''


def self_prompt_sorting_response(prompt: str, scenario: str = "") -> str | None:
    if not is_sorting_self_prompt(prompt, scenario):
        return None
    normalized = (prompt or "").lower()

    if "fixed sop development run" in normalized:
        return sorting_task_manifest(goal="General Auto Development self-prompt sorting run")

    if (
        "planning the next prompts for a cli coding agent" in normalized
        or "human-style planner for a cli agent session" in normalized
        or "generate execution prompts" in normalized
        or "step: generate_task_prompts" in normalized
    ):
        return sorting_task_manifest(goal="Adaptive Auto Workflow self-prompt sorting run")

    if "review the completed sop development result" in normalized or "review the completed project change" in normalized:
        return sorting_review_json()

    if (
        "complete this sop task" in normalized
        or "execute the current ai-generated prompt" in normalized
        or "complete this task" in normalized
        or "step: build" in normalized
        or "step: auto_generation" in normalized
        or "current workflow step: build" in normalized
        or "current workflow step: auto_generation" in normalized
    ):
        return sorting_file_blocks()

    if (
        "step: generate_tests" in normalized
        or "current workflow step: generate_tests" in normalized
        or "you are generating automated tests" in normalized
        or "add focused automated tests" in normalized
        or "create focused automated tests" in normalized
    ) and "review the completed" not in normalized:
        return f"""Status: READY

FILE: tests/test_sorting_algorithms.py
CONTENT:
{sorting_tests()}END_FILE
"""

    return None
