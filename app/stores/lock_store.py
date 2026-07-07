from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.workflow_runtime.run_lifecycle import (
    cleanup_stale_project_lock,
    clear_project_lock,
    read_project_lock,
    write_project_lock,
)


class LockStore(Protocol):
    def read_project_lock(self, project_path: str | Path) -> dict[str, Any] | None: ...
    def write_project_lock(self, run: dict[str, Any]) -> dict[str, Any]: ...
    def clear_project_lock(self, run_or_project_path: dict[str, Any] | str | Path, *, run_id: str | None = None) -> bool: ...
    def cleanup_stale_project_lock(self, project_path: str | Path, data: dict[str, Any]) -> dict[str, Any]: ...


class FileLockStore:
    def read_project_lock(self, project_path: str | Path) -> dict[str, Any] | None:
        return read_project_lock(project_path)

    def write_project_lock(self, run: dict[str, Any]) -> dict[str, Any]:
        return write_project_lock(run)

    def clear_project_lock(self, run_or_project_path: dict[str, Any] | str | Path, *, run_id: str | None = None) -> bool:
        return clear_project_lock(run_or_project_path, run_id=run_id)

    def cleanup_stale_project_lock(self, project_path: str | Path, data: dict[str, Any]) -> dict[str, Any]:
        return cleanup_stale_project_lock(project_path, data)
