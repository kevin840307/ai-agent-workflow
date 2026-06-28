from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from app.runtime_errors import ValidationError, WorkflowError
from app.runtime_paths import read_text, write_text


def require_sections(text: str, sections: Iterable[str], label: str) -> None:
    missing = [section for section in sections if f"## {section}" not in text]
    if missing:
        raise ValidationError(f"{label} missing sections: {', '.join(missing)}")


def ids_with_prefix(text: str, prefix: str) -> set[str]:
    return set(re.findall(rf"\b{prefix}-\d{{3}}\b", text))


def acceptance_criteria_items(spec: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in spec.splitlines():
        match = re.search(r"\b(AC-\d{3})\b[:.\-\s]*(.*)", line)
        if match:
            items.append((match.group(1), match.group(2).strip() or "Acceptance criterion"))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for ac_id, text in items:
        if ac_id not in seen:
            seen.add(ac_id)
            unique.append((ac_id, text))
    return unique


def synthesize_todo_from_spec(output_dir: Path) -> str:
    spec = read_text(output_dir / "spec.md")
    ac_items = acceptance_criteria_items(spec)
    if not ac_items:
        ac_items = [("AC-001", "Complete the requested workflow requirement")]

    todo_lines = ["# Todo", "", "## Todo List"]
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TODO-{index:03d} Implement and verify {ac_id}: {text}")

    todo_lines.extend(["", "## Test Plan"])
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TEST-{index:03d} Test that {ac_id} is satisfied: {text}")

    covered = ", ".join(ac_id for ac_id, _ in ac_items)
    todo_lines.extend(
        [
            "",
            "## Done Criteria",
            f"- All acceptance criteria are implemented and tested: {covered}.",
            "- The workflow can proceed through review, build, test, and final review without validation errors.",
        ]
    )
    return "\n".join(todo_lines) + "\n"


def synthesize_spec_from_requirement(requirement: str) -> str:
    clean_requirement = requirement.strip() or "Complete the requested project task."
    return (
        "# Specification\n\n"
        "## Goal\n"
        f"- {clean_requirement}\n\n"
        "## Scope\n"
        "- Implement the requested behavior in the selected project path.\n"
        "- Keep the solution small, readable, and suitable for automated testing.\n\n"
        "## Out of Scope\n"
        "- Do not add unrelated features or broad refactors.\n"
        "- Do not change files outside the selected project path.\n\n"
        "## Input\n"
        f"- User requirement: {clean_requirement}\n"
        "- Existing project files, if any.\n\n"
        "## Output\n"
        "- Source code implementing the requested behavior.\n"
        "- Separate automated tests for the behavior.\n\n"
        "## Rules\n"
        "- Tests must be stored separately from production code.\n"
        "- Build output must use FILE/CONTENT/END_FILE blocks when creating or modifying files.\n"
        "- Prefer simple standard-library code unless the project already uses a framework.\n\n"
        "## Acceptance Criteria\n"
        f"- AC-001: The project implements the requested behavior: {clean_requirement}\n"
        "- AC-002: Automated tests verify the main expected behavior.\n"
        "- AC-003: The test command completes successfully.\n\n"
        "## Unknowns\n"
        "- None blocking. Use reasonable defaults for unspecified implementation details.\n"
    )


def requirement_mentions_language(requirement: str) -> bool:
    lower = requirement.lower()
    keywords = [
        "python",
        ".py",
        "javascript",
        "typescript",
        "node",
        "java",
        "c#",
        "c++",
        "go",
        "rust",
        "php",
        "ruby",
        "程式",
        "語言",
    ]
    return any(keyword in lower for keyword in keywords)


def should_ask_for_spec_input(requirement: str, project_dir: Path) -> bool:
    return not project_has_user_files(project_dir) and not requirement_mentions_language(requirement)


def requirement_is_python_bubble_sort(requirement: str) -> bool:
    lower = requirement.lower()
    mentions_python = "python" in lower or ".py" in lower
    mentions_bubble = "bubble" in lower or "泡沫" in requirement or "氣泡" in requirement
    return mentions_python and mentions_bubble


def synthesize_build_from_requirement(requirement: str) -> str:
    if not requirement_is_python_bubble_sort(requirement):
        return ""
    return (
        "FILE: bubble_sort.py\n"
        "CONTENT:\n"
        "from __future__ import annotations\n\n\n"
        "def bubble_sort(items):\n"
        "    \"\"\"Return a sorted copy of items using bubble sort.\"\"\"\n"
        "    result = list(items)\n"
        "    n = len(result)\n"
        "    for end in range(n - 1, 0, -1):\n"
        "        swapped = False\n"
        "        for index in range(end):\n"
        "            if result[index] > result[index + 1]:\n"
        "                result[index], result[index + 1] = result[index + 1], result[index]\n"
        "                swapped = True\n"
        "        if not swapped:\n"
        "            break\n"
        "    return result\n"
        "END_FILE\n"
    )


def synthesize_tests_from_requirement(requirement: str) -> str:
    if not requirement_is_python_bubble_sort(requirement):
        return ""
    return (
        "FILE: tests/test_bubble_sort.py\n"
        "CONTENT:\n"
        "from bubble_sort import bubble_sort\n\n\n"
        "def test_bubble_sort_orders_numbers():\n"
        "    assert bubble_sort([3, 1, 2]) == [1, 2, 3]\n\n\n"
        "def test_bubble_sort_handles_duplicates():\n"
        "    assert bubble_sort([4, 2, 4, 1]) == [1, 2, 4, 4]\n\n\n"
        "def test_bubble_sort_handles_empty_list():\n"
        "    assert bubble_sort([]) == []\n\n\n"
        "def test_bubble_sort_does_not_mutate_input():\n"
        "    values = [2, 1]\n"
        "    assert bubble_sort(values) == [1, 2]\n"
        "    assert values == [2, 1]\n"
        "END_FILE\n"
    )


def classify_test_retry_target(project_dir: Path, test_result: str) -> str:
    text = test_result or ""
    lower = text.lower()
    test_collection_or_import_problem = any(
        marker in lower
        for marker in [
            "error collecting",
            "importerror while importing test module",
            "syntaxerror",
            "no module named",
        ]
    )
    if test_collection_or_import_problem:
        return "generate_tests"
    return "build"


def failure_feedback_for_step(all_feedback: str, step_key: str) -> str:
    if not all_feedback.strip():
        return ""
    pattern = re.compile(
        rf"^## Retry Feedback for {re.escape(step_key)}\s*$.*?(?=^## Retry Feedback for |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    blocks = [match.group(0).strip() for match in pattern.finditer(all_feedback)]
    return "\n\n".join(blocks)


def project_file_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    if not project_dir.exists():
        return snapshot
    ignored_dirs = {".git", ".qwen-workflow", "__pycache__", "node_modules", ".venv", "venv"}
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.relative_to(project_dir).parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(project_dir))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def project_has_user_files(project_dir: Path) -> bool:
    return bool(project_file_snapshot(project_dir))


def project_overview(project_dir: Path, limit: int = 180) -> str:
    snapshot = project_file_snapshot(project_dir)
    if not snapshot:
        return "Project appears empty."
    paths = sorted(snapshot)
    shown = paths[:limit]
    lines = [f"- {path}" for path in shown]
    if len(paths) > limit:
        lines.append(f"- ... {len(paths) - limit} more files")
    return "\n".join(lines)


def snapshot_changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> bool:
    return before != after


def extract_build_files(build_result: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    pattern = re.compile(r"^FILE:\s*(?P<path>.+?)\s*\r?\nCONTENT:\r?\n(?P<content>.*?)(?=^END_FILE\s*$)", re.DOTALL | re.MULTILINE)
    for match in pattern.finditer(build_result):
        rel_path = match.group("path").strip().strip("`").replace("\\", "/")
        content = match.group("content")
        content = re.sub(r"\r?\n$", "", content)
        files.append((rel_path, content + "\n"))
    return files


def apply_build_files(project_dir: Path, build_result: str) -> list[Path]:
    written: list[Path] = []
    project_root = project_dir.resolve()
    for rel_path, content in extract_build_files(build_result):
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts or ".qwen-workflow" in rel.parts:
            raise WorkflowError(f"build output contains unsafe file path: {rel_path}")
        target = (project_root / rel).resolve()
        if target != project_root and project_root not in target.parents:
            raise WorkflowError(f"build output path escapes Project Path: {rel_path}")
        write_text(target, content)
        written.append(target)
    return written


def normalized_rel_path(rel_path: str) -> str:
    return rel_path.strip().strip("`").replace("\\", "/")


def is_test_file_path(rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    path = Path(normalized)
    parts = path.parts
    if not parts:
        return False
    if parts[0] != "tests":
        return False
    name = path.name
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def validate_generated_test_files(files: list[tuple[str, str]]) -> None:
    if not files:
        raise WorkflowError("generate_tests did not create any test files. Qwen test output must include FILE/CONTENT/END_FILE blocks.")
    invalid = [rel_path for rel_path, _ in files if not is_test_file_path(rel_path)]
    if invalid:
        raise WorkflowError(
            "generate_tests can only write pytest files under tests/ "
            f"(tests/test_*.py or tests/conftest.py). Invalid file(s): {', '.join(invalid)}"
        )


def validate_build_files_are_not_tests(files: list[tuple[str, str]]) -> None:
    invalid = [rel_path for rel_path, _ in files if is_test_file_path(rel_path) or Path(normalized_rel_path(rel_path)).name.startswith("test_")]
    if invalid:
        raise WorkflowError(
            "build must not create or modify test files. Generate Tests owns tests/. "
            f"Invalid build file(s): {', '.join(invalid)}"
        )
