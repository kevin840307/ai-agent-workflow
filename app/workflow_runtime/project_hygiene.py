from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Any

_IGNORE_DIRS = {".git", ".ai-workflow", ".qwen-workflow", ".venv", "venv", "node_modules", "__pycache__"}
_COMMON_FUNCTIONS = {"main", "run", "setup", "teardown", "create", "build", "load", "save", "get", "set"}


def inspect_project_hygiene(project_dir: Path) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    python_files = [
        path
        for path in project_dir.rglob("*.py")
        if path.is_file() and not any(part in _IGNORE_DIRS for part in path.relative_to(project_dir).parts)
    ]
    production = [path for path in python_files if not _is_test_file(project_dir, path)]
    tests = [path for path in python_files if _is_test_file(project_dir, path)]

    errors: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {
        "python_file_count": len(python_files),
        "production_files": [_rel(project_dir, path) for path in production],
        "test_files": [_rel(project_dir, path) for path in tests],
    }

    root_tests = [_rel(project_dir, path) for path in tests if path.parent == project_dir and path.name.startswith("test_")]
    if root_tests and (project_dir / "tests").is_dir():
        errors.append("Root-level pytest files duplicate the tests/ layout: " + ", ".join(root_tests))

    if (project_dir / "run_tests.py").is_file() and any((project_dir / "tests").glob("test_*.py")):
        warnings.append("run_tests.py exists alongside a pytest suite; keep one canonical test entry point unless both are required.")

    production_defs = _function_index(project_dir, production)
    test_defs = _function_index(project_dir, tests)
    embedded = sorted(name for name in test_defs if name in production_defs and name not in _COMMON_FUNCTIONS and not name.startswith("test_"))
    if embedded:
        errors.append("Test files redefine production functions instead of importing them: " + ", ".join(embedded[:10]))

    # Small local projects should not contain multiple root modules defining the
    # same non-trivial public function. This catches duplicate generated outputs
    # such as bubble_sort.py + sort.py while avoiding large framework projects.
    duplicates: dict[str, list[str]] = {}
    if len(production) <= 20:
        for name, files in production_defs.items():
            root_files = sorted({file for file in files if "/" not in file})
            if len(root_files) > 1 and name not in _COMMON_FUNCTIONS and not name.startswith("_"):
                duplicates[name] = root_files
    if duplicates:
        details = "; ".join(f"{name}: {', '.join(files)}" for name, files in sorted(duplicates.items()))
        errors.append("Duplicate public implementations detected: " + details)

    evidence["duplicate_functions"] = duplicates
    evidence["root_test_files"] = root_tests
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "evidence": evidence,
    }


def _function_index(project_dir: Path, files: list[Path]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Ignore tiny wrappers/dunder helpers.
                if len(node.body) < 2 or node.name.startswith("__"):
                    continue
                index[node.name].append(_rel(project_dir, path))
    return dict(index)


def _is_test_file(project_dir: Path, path: Path) -> bool:
    rel = path.relative_to(project_dir)
    return path.name.startswith("test_") or "tests" in rel.parts


def _rel(project_dir: Path, path: Path) -> str:
    return path.relative_to(project_dir).as_posix()
