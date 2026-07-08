from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

IGNORED_SNAPSHOT_DIRS = {".ai-workflow", ".qwen", ".qwen-workflow", ".git", "__pycache__", ".pytest_cache"}


def iter_project_snapshot_files(project_dir: Path) -> Iterator[Path]:
    """Yield project files for E2E snapshots while pruning heavy runtime dirs."""
    root = Path(project_dir)
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in IGNORED_SNAPSHOT_DIRS]
        current_path = Path(current)
        for name in sorted(files):
            path = current_path / name
            if path.is_file():
                yield path


def copy_pruned_tree(src: Path, dst: Path) -> None:
    """Copy a tree for E2E evidence while pruning recursive/heavy runtime dirs."""
    src = Path(src)
    dst = Path(dst)
    for current, dirs, files in os.walk(src):
        dirs[:] = [name for name in dirs if name not in IGNORED_SNAPSHOT_DIRS]
        current_path = Path(current)
        rel_dir = current_path.relative_to(src)
        target_dir = dst / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            path = current_path / name
            if not path.is_file():
                continue
            target = target_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                import shutil
                shutil.copy2(path, target)
            except OSError:
                continue
