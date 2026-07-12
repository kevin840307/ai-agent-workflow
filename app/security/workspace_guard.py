from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from typing import Mapping

from fastapi import HTTPException

from app.runtime_modules.errors import WorkflowError

PROJECT_WORKFLOW_DIR = ".ai-workflow"
LEGACY_WORKFLOW_DIR = ".qwen-workflow"
RESERVED_AGENT_WRITE_DIRS = {PROJECT_WORKFLOW_DIR, LEGACY_WORKFLOW_DIR, ".git", ".qwen"}
FILE_BLOCK_PATH_MARKERS = {"file", "content", "start_file", "end_file", "begin_file"}


def canonical_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_within(root: str | Path, candidate: str | Path) -> bool:
    root_path = canonical_path(root)
    candidate_path = canonical_path(candidate)
    return candidate_path == root_path or root_path in candidate_path.parents


def ensure_within_project(project_root: str | Path, target: str | Path, *, action: str = "write") -> Path:
    project_path = canonical_path(project_root)
    target_path = canonical_path(target)
    if not is_within(project_path, target_path):
        raise WorkflowError(f"Refusing to {action} outside Project Path. target={target_path}, project={project_path}")
    return target_path


def ensure_http_within_project(project_root: str | Path | None, target: str | Path, *, action: str = "write") -> Path:
    if not project_root:
        raise HTTPException(status_code=400, detail="project_path is required for project-scoped writes")
    project_path = canonical_path(project_root)
    target_path = canonical_path(target)
    if not is_within(project_path, target_path):
        raise HTTPException(status_code=400, detail=f"Refusing to {action} outside Project Path: {target_path}")
    return target_path


def unsafe_relative_path_reason(raw_path: str, *, reserved_dirs: set[str] | None = None) -> str | None:
    raw = str(raw_path or "").strip().strip("`")
    if not raw:
        return "empty path"
    decoded = unquote(raw).replace("\\", "/")
    path = Path(decoded)
    win_path = PureWindowsPath(decoded)
    if decoded.startswith("/") or path.is_absolute() or win_path.is_absolute() or win_path.drive or decoded.startswith("//"):
        return "absolute path"
    parts = [part for part in decoded.split("/") if part not in {"", "."}]
    normalized = "/".join(parts).lower()
    if normalized in {"relative/path.ext", "relative_path.ext"} or normalized.startswith(("relative/path/", "relative_path/")):
        return "placeholder relative/path output is not a real project file"
    if normalized.startswith("path_to_") or normalized.startswith("example."):
        return "placeholder output path is not a real project file"
    if normalized == "opencode.json":
        return "managed agent guard config: opencode.json"
    marker_parts = {
        token
        for part in parts
        for token in re.split(r"[^a-z0-9_]+", part.lower())
        if token
    }
    if marker_parts & FILE_BLOCK_PATH_MARKERS:
        return "file block marker leaked into path"
    if any(part.strip() == ".." for part in parts):
        return "parent directory traversal"
    reserved = reserved_dirs if reserved_dirs is not None else RESERVED_AGENT_WRITE_DIRS
    for part in parts:
        if part in reserved:
            return f"reserved directory: {part}"
    return None


def resolve_project_relative_write(project_root: str | Path, rel_path: str, *, reserved_dirs: set[str] | None = None, label: str = "write") -> Path:
    project_path = canonical_path(project_root)
    raw = str(rel_path or "").strip().strip("`")
    decoded = unquote(raw).replace("\\", "/")
    candidate = Path(decoded)
    win_candidate = PureWindowsPath(decoded)
    project_win = PureWindowsPath(str(project_path))
    if decoded.startswith("//") and not str(project_win).startswith("\\\\"):
        # Resolving a UNC path can perform network I/O and fail before the
        # workspace guard can return a controlled WorkflowError.
        raise WorkflowError(f"{label} contains unsafe file path (UNC path outside Project Path): {rel_path}")
    if decoded.startswith("/") or candidate.is_absolute() or win_candidate.is_absolute() or win_candidate.drive or decoded.startswith("//"):
        target = canonical_path(decoded)
        if not is_within(project_path, target):
            raise WorkflowError(f"{label} contains unsafe file path (absolute path outside Project Path): {rel_path}")
        rel_path = target.relative_to(project_path).as_posix()
    if _looks_like_drive_stripped_absolute_path(project_path, rel_path):
        raise WorkflowError(f"{label} contains unsafe file path (drive-stripped absolute path): {rel_path}")
    reason = unsafe_relative_path_reason(rel_path, reserved_dirs=reserved_dirs)
    if reason:
        raise WorkflowError(f"{label} contains unsafe file path ({reason}): {rel_path}")
    relative = Path(unquote(str(rel_path).strip().strip("`")).replace("\\", "/"))
    target = (project_path / relative).resolve()
    return ensure_within_project(project_path, target, action=label)


def _looks_like_drive_stripped_absolute_path(project_path: Path, rel_path: str) -> bool:
    rel_parts = [part.lower() for part in str(rel_path or "").replace("\\", "/").split("/") if part and part != "."]
    root_parts = [part.lower() for part in project_path.parts if part and part not in {project_path.anchor}]
    if len(rel_parts) < 2 or len(root_parts) < 2:
        return False
    return rel_parts[:2] == root_parts[:2]


def guarded_write_text(project_root: str | Path, path: str | Path, content: str, write_func) -> None:
    target = ensure_within_project(project_root, path, action="write")
    write_func(target, content)


def workspace_env(*, project_path: str | Path, workspace_path: str | Path | None = None, run_id: str | None = None, write_policy: str = "project_only") -> dict[str, str]:
    project = canonical_path(project_path)
    workspace = canonical_path(workspace_path) if workspace_path else project / PROJECT_WORKFLOW_DIR
    env = {
        "AI_WORKFLOW_PROJECT_PATH": str(project),
        "AI_WORKFLOW_WRITE_ROOT": str(project),
        "AI_WORKFLOW_READ_POLICY": "unrestricted",
        "AI_WORKFLOW_WRITE_POLICY": write_policy,
        "AI_WORKFLOW_WORKSPACE": str(workspace),
        "AI_WORKFLOW_PROJECT_WORKFLOW_DIR": PROJECT_WORKFLOW_DIR,
    }
    if run_id:
        env["AI_WORKFLOW_RUN_ID"] = str(run_id)
    return env


def apply_workspace_env(base_env: Mapping[str, str] | None, *, project_path: str | Path, workspace_path: str | Path | None = None, run_id: str | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env.update(workspace_env(project_path=project_path, workspace_path=workspace_path, run_id=run_id))
    return env
