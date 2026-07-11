from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.core.paths import utc_now, write_text

EXCLUDED_PARTS = {".git", ".ai-workflow", ".qwen-workflow", ".qwen", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", "target", "bin", "obj", "dist", "build"}


def _safe_task_id(task_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(task_id or "task"))


def _iter_project_files(project_dir: Path):
    max_file_bytes = int(os.environ.get("AIWF_TASK_CHECKPOINT_MAX_FILE_BYTES", str(8 * 1024 * 1024)))
    for path in project_dir.rglob("*"):
        # Checkpoints never follow symlinks. A project-local link may target a
        # secret or a very large file outside Project Path.
        if path.is_symlink() or not path.is_file() or any(part in EXCLUDED_PARTS for part in path.relative_to(project_dir).parts):
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        yield path


def _prune_old_checkpoints(run: dict[str, Any], checkpoint_dir: Path) -> None:
    keep = max(2, int(os.environ.get("AIWF_TASK_CHECKPOINT_KEEP", "8")))
    records = list(run.get("task_checkpoints") or [])
    if len(records) <= keep:
        return
    stale = records[:-keep]
    for record in stale:
        checkpoint_id = str(record.get("id") or "")
        if not checkpoint_id:
            continue
        for suffix in (".zip", ".json"):
            (checkpoint_dir / f"{checkpoint_id}{suffix}").unlink(missing_ok=True)
    run["task_checkpoints"] = records[-keep:]


def create_task_checkpoint(
    run: dict[str, Any],
    *,
    task_id: str,
    step_key: str,
    project_dir: Path,
    changed_files: list[tuple[str, str]] | list[str] | None = None,
) -> dict[str, Any]:
    workspace = Path(run["workspace"])
    checkpoint_dir = workspace / ".workflow" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    sequence = len(run.get("task_checkpoints") or []) + 1
    checkpoint_id = f"task-{sequence:03d}-{_safe_task_id(task_id)}"
    archive = checkpoint_dir / f"{checkpoint_id}.zip"
    manifest_files: list[dict[str, Any]] = []
    skipped_files: list[str] = []
    max_total_bytes = int(os.environ.get("AIWF_TASK_CHECKPOINT_MAX_BYTES", str(96 * 1024 * 1024)))
    total_bytes = 0
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_project_files(project_dir):
            rel = path.relative_to(project_dir).as_posix()
            data = path.read_bytes()
            if total_bytes + len(data) > max_total_bytes:
                skipped_files.append(rel)
                continue
            total_bytes += len(data)
            zf.writestr(rel, data)
            manifest_files.append({"path": rel, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    changed_paths = []
    for item in changed_files or []:
        changed_paths.append(str(item[0] if isinstance(item, tuple) else item).replace("\\", "/"))
    record = {
        "id": checkpoint_id,
        "kind": "task_completed",
        "task_id": task_id,
        "step_key": step_key,
        "status": "passed",
        "created_at": utc_now(),
        "archive": f".workflow/checkpoints/{archive.name}",
        "file_count": len(manifest_files),
        "archive_bytes": archive.stat().st_size if archive.exists() else 0,
        "source_bytes": total_bytes,
        "complete": not skipped_files,
        "skipped_file_count": len(skipped_files),
        "changed_files": changed_paths[:200],
        "session_roles": dict(run.get("role_session_ids") or {}),
        "retry_counters": dict(run.get("recovery_counters") or {}),
    }
    write_text(checkpoint_dir / f"{checkpoint_id}.json", json.dumps({**record, "files": manifest_files, "skipped_files": skipped_files[:200]}, indent=2, ensure_ascii=False))
    run.setdefault("task_checkpoints", []).append(record)
    _prune_old_checkpoints(run, checkpoint_dir)
    run["last_task_checkpoint_id"] = checkpoint_id
    tasks = run.setdefault("tasks", [])
    existing = next((item for item in tasks if str(item.get("id")) == str(task_id)), None)
    if existing is None:
        existing = {"id": task_id}
        tasks.append(existing)
    existing.update({"status": "passed", "step_key": step_key, "checkpoint_id": checkpoint_id, "updated_at": record["created_at"]})
    return record


def restore_task_checkpoint(run: dict[str, Any], checkpoint_id: str, *, project_dir: Path | None = None) -> dict[str, Any]:
    project = (project_dir or Path(run.get("project_path") or "")).expanduser().resolve()
    workspace = Path(run["workspace"])
    checkpoint_dir = workspace / ".workflow" / "checkpoints"
    archive = checkpoint_dir / f"{checkpoint_id}.zip"
    manifest_path = checkpoint_dir / f"{checkpoint_id}.json"
    if not archive.is_file():
        raise FileNotFoundError(f"Task checkpoint archive not found: {checkpoint_id}")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if manifest.get("complete") is False:
            raise ValueError(
                f"Task checkpoint {checkpoint_id} is metadata-only/incomplete because the project exceeded checkpoint limits."
            )
    for path in list(_iter_project_files(project)):
        path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "r") as zf:
        for member in zf.infolist():
            target = (project / member.filename).resolve()
            if project not in target.parents and target != project:
                raise ValueError(f"Unsafe checkpoint path: {member.filename}")
        zf.extractall(project)
    for path in sorted(project.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()) and path != project:
            path.rmdir()
    return {"restored": True, "checkpoint_id": checkpoint_id, "project_path": str(project)}


__all__ = ["create_task_checkpoint", "restore_task_checkpoint"]
