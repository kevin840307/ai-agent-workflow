from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.paths import write_text

_CACHE_DIRS = {"__pycache__", ".pytest_cache"}


def load_run_baseline_paths(run_workspace: Path) -> set[str]:
    """Return paths that existed when the workflow run started."""
    path = run_workspace / ".workflow" / "project-snapshot-before.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return set()
    files = payload.get("files") if isinstance(payload, dict) else None
    return {str(value).replace("\\", "/") for value in files} if isinstance(files, dict) else set()


def repair_run_owned_test_layout(project_dir: Path, run_workspace: Path) -> dict[str, Any]:
    """Deterministically remove test-layout conflicts created by the current run.

    A root ``test_*.py`` is removed only when it did not exist in the run
    baseline and a canonical counterpart exists under ``tests/``. Empty
    run-created root tests may also be removed when any canonical pytest suite
    exists. User-owned files that existed before the run are never deleted.
    """
    project_root = project_dir.expanduser().resolve()
    baseline_paths = load_run_baseline_paths(run_workspace)
    canonical_tests = sorted(
        path
        for path in (project_root / "tests").rglob("test_*.py")
        if path.is_file()
    ) if (project_root / "tests").is_dir() else []

    removed: list[str] = []
    preserved: list[dict[str, str]] = []
    candidates: list[dict[str, Any]] = []

    for root_test in sorted(project_root.glob("test_*.py")):
        if not root_test.is_file():
            continue
        rel = root_test.relative_to(project_root).as_posix()
        matching = project_root / "tests" / root_test.name
        try:
            size = root_test.stat().st_size
        except OSError:
            size = -1
        run_owned = rel not in baseline_paths
        reason = ""
        if matching.is_file():
            reason = "canonical counterpart exists under tests/"
        elif size == 0 and canonical_tests:
            reason = "empty run-created root test duplicates the tests/ layout"

        candidates.append(
            {
                "path": rel,
                "run_owned": run_owned,
                "size_bytes": size,
                "matching_test": matching.relative_to(project_root).as_posix() if matching.is_file() else None,
                "reason": reason or "no deterministic conflict",
            }
        )

        if not reason:
            continue
        if not run_owned:
            preserved.append({"path": rel, "reason": "file existed before this run"})
            continue
        try:
            root_test.unlink()
            removed.append(rel)
        except OSError as exc:
            preserved.append({"path": rel, "reason": f"could not remove: {exc}"})

    removed_caches = _remove_test_caches(project_root)
    status = "REPAIRED" if removed or removed_caches else "CLEAN"
    return {
        "schema": "aiwf.test-layout-repair.v1",
        "status": status,
        "project_path": str(project_root),
        "baseline_available": bool(baseline_paths),
        "removed_files": removed,
        "removed_cache_dirs": removed_caches,
        "preserved_files": preserved,
        "candidates": candidates,
    }


def write_test_layout_repair_report(run_workspace: Path, result: dict[str, Any]) -> Path:
    output_dir = run_workspace / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "test-layout-repair.json"
    merged = dict(result)
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            previous = {}
        if isinstance(previous, dict) and previous.get("schema") == result.get("schema"):
            for key in ("removed_files", "removed_cache_dirs"):
                merged[key] = sorted(set(previous.get(key) or []) | set(result.get(key) or []))
            for key in ("preserved_files", "candidates"):
                items: list[Any] = []
                seen: set[str] = set()
                for item in [*(previous.get(key) or []), *(result.get(key) or [])]:
                    marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    items.append(item)
                merged[key] = items
            if merged.get("removed_files") or merged.get("removed_cache_dirs"):
                merged["status"] = "REPAIRED"
    write_text(path, json.dumps(merged, indent=2, ensure_ascii=False))
    return path


def is_pytest_import_mismatch(text: str) -> bool:
    lower = str(text or "").lower()
    return "import file mismatch" in lower or (
        "imported module" in lower and "is not the same as the test file" in lower
    )


def _remove_test_caches(project_root: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(project_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir() or path.name not in _CACHE_DIRS:
            continue
        try:
            rel = path.relative_to(project_root).as_posix()
            shutil.rmtree(path)
            removed.append(rel)
        except (OSError, ValueError):
            continue
    return removed


__all__ = [
    "is_pytest_import_mismatch",
    "load_run_baseline_paths",
    "repair_run_owned_test_layout",
    "write_test_layout_repair_report",
]
