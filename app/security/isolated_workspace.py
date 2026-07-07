from __future__ import annotations

import filecmp
import shutil
from pathlib import Path
from typing import Iterable

IGNORED_DIRS = {".git", ".ai-workflow", ".qwen-workflow", ".qwen", "__pycache__", ".pytest_cache"}


def create_isolated_project_copy(project_dir: Path, workspace_dir: Path, *, ignored_dirs: Iterable[str] = IGNORED_DIRS) -> Path:
    """Copy a project into a run-local agent workspace.

    This helper is intentionally opt-in: existing workflow runs still use the
    selected project path for compatibility, while productized deployments can
    point the agent at the returned copy and apply an reviewed patch afterward.
    """
    project = Path(project_dir).expanduser().resolve()
    workspace = Path(workspace_dir).expanduser().resolve()
    target = workspace / "agent-project"
    ignored = set(ignored_dirs)
    if target.exists():
        shutil.rmtree(target)

    def ignore(_root: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored}

    shutil.copytree(project, target, ignore=ignore)
    return target


def changed_project_files(original_dir: Path, isolated_dir: Path) -> list[str]:
    """Return project-relative files that differ between original and isolated copy."""
    original = Path(original_dir).expanduser().resolve()
    isolated = Path(isolated_dir).expanduser().resolve()
    paths: set[str] = set()
    for root in [original, isolated]:
        for path in root.rglob("*"):
            if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                paths.add(path.relative_to(root).as_posix())
            except ValueError:
                continue
    changed: list[str] = []
    for rel in sorted(paths):
        left = original / rel
        right = isolated / rel
        if not left.exists() or not right.exists() or not filecmp.cmp(left, right, shallow=False):
            changed.append(rel)
    return changed


def apply_isolated_changes(original_dir: Path, isolated_dir: Path, changed_files: Iterable[str]) -> list[Path]:
    """Apply selected reviewed changes from an isolated copy back to the project."""
    original = Path(original_dir).expanduser().resolve()
    isolated = Path(isolated_dir).expanduser().resolve()
    written: list[Path] = []
    for rel in changed_files:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"Unsafe relative path: {rel}")
        source = (isolated / rel_path).resolve()
        target = (original / rel_path).resolve()
        try:
            source.relative_to(isolated)
            target.relative_to(original)
        except ValueError as exc:
            raise ValueError(f"Unsafe relative path: {rel}") from exc
        if not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(target)
    return written
