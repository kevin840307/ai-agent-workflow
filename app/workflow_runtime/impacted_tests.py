from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

_IGNORED_PARTS = {".git", ".ai-workflow", ".workflow", "node_modules", ".venv", "venv", "dist", "build"}


def _normalized_paths(changed_files: Iterable[dict[str, Any] | str] | None) -> list[str]:
    result: list[str] = []
    for item in changed_files or []:
        raw = item.get("path") if isinstance(item, dict) else item
        value = str(raw or "").replace("\\", "/").lstrip("./")
        if value and value not in result:
            result.append(value)
    return result


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    return (
        lower.startswith("tests/")
        or "/test/" in f"/{lower}/"
        or "/tests/" in f"/{lower}/"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
        or name.endswith("test.java")
        or name.endswith("tests.java")
        or name.endswith("tests.cs")
        or name.endswith("test.cs")
    )


def _candidate_tests(project: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(project).as_posix()
        except ValueError:
            continue
        if any(part in _IGNORED_PARTS for part in Path(rel).parts):
            continue
        if _is_test_path(rel):
            candidates.append(path)
    return candidates


def identify_impacted_tests(
    project_path: str | Path,
    changed_files: Iterable[dict[str, Any] | str] | None,
    *,
    max_tests: int = 20,
) -> dict[str, Any]:
    """Map changed production paths to likely existing tests without modifying code.

    This is a conservative accelerator. The full project test gate remains the
    final source of truth, so uncertain matches never replace the full suite.
    """
    project = Path(project_path).expanduser().resolve()
    changed = [path for path in _normalized_paths(changed_files) if not _is_test_path(path)]
    tests = _candidate_tests(project)
    scored: list[tuple[int, str, list[str]]] = []
    for test_path in tests:
        rel = test_path.relative_to(project).as_posix()
        test_lower = rel.lower()
        reasons: list[str] = []
        score = 0
        try:
            content = test_path.read_text(encoding="utf-8", errors="replace").lower()[:120_000]
        except OSError:
            content = ""
        for source in changed:
            source_path = Path(source)
            stem = source_path.stem.lower()
            if stem in {"__init__", "index", "main", "app"}:
                stem_signal = ""
            else:
                stem_signal = stem
            if stem_signal and re.search(rf"(^|[^a-z0-9_]){re.escape(stem_signal)}([^a-z0-9_]|$)", test_lower):
                score += 6
                reasons.append(f"filename:{source}")
            elif stem_signal and re.search(rf"(^|[^a-z0-9_]){re.escape(stem_signal)}([^a-z0-9_]|$)", content):
                score += 4
                reasons.append(f"reference:{source}")
            source_parts = [part.lower() for part in source_path.parts[:-1] if len(part) >= 3 and part.lower() not in {"src", "lib", "app", "main"}]
            shared = sum(1 for part in source_parts if part in test_lower)
            if shared:
                score += min(3, shared)
                reasons.append(f"module:{source}")
        if score > 0:
            scored.append((score, rel, list(dict.fromkeys(reasons))))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = scored[: max(1, int(max_tests))]
    return {
        "schema": "aiwf.impacted-tests.v1",
        "changed_files": changed,
        "tests": [{"path": rel, "score": score, "reasons": reasons} for score, rel, reasons in selected],
        "confidence": "high" if selected and selected[0][0] >= 6 else "medium" if selected else "none",
        "full_suite_required": True,
    }


__all__ = ["identify_impacted_tests"]
