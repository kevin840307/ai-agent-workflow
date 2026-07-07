from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import utc_now, write_text
from app.runtime_modules.run_owner import current_run_owner, owner_matches_current_process, owner_process_is_alive
from app.security.workspace_guard import PROJECT_WORKFLOW_DIR

ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_input", "cancelling"}
TERMINAL_RUN_STATUSES = {"done", "failed", "cancelled"}
LOCK_FILE_NAME = "project-run-lock.json"


def run_project_path(run: dict[str, Any]) -> str:
    return str(run.get("original_project_path") or run.get("project_path") or "")


def project_workflow_dir(project_path: str | Path) -> Path:
    return Path(project_path) / PROJECT_WORKFLOW_DIR


def project_lock_path(project_path: str | Path) -> Path:
    return project_workflow_dir(project_path) / LOCK_FILE_NAME


def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
    if not left or not right:
        return False
    try:
        return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()
    except OSError:
        return str(left).casefold() == str(right).casefold()


def is_active_run(run: dict[str, Any] | None) -> bool:
    return bool(run and run.get("status") in ACTIVE_RUN_STATUSES)


def is_terminal_run(run: dict[str, Any] | None) -> bool:
    return bool(run and run.get("status") in TERMINAL_RUN_STATUSES)


def active_run_owner_is_live(run: dict[str, Any] | None) -> bool:
    """Return True when an active run should still block project execution.

    Runs without owner metadata are treated as live for backward compatibility.
    Runs owned by a dead foreign process are stale and can be recovered instead
    of blocking a new workflow forever after crashes or abrupt test shutdowns.
    """
    if not is_active_run(run):
        return False
    owner = (run or {}).get("run_owner")
    if not owner:
        return True
    if owner_matches_current_process(owner):
        return True
    return owner_process_is_alive(owner)


def mark_stale_active_run_interrupted(run: dict[str, Any], *, reason: str | None = None) -> dict[str, Any]:
    message = reason or "Workflow owner process is no longer alive; run was recovered as interrupted."
    run["status"] = "failed"
    run["error"] = message
    run["error_code"] = "INTERRUPTED"
    run["ended_at"] = utc_now()
    run["updated_at"] = utc_now()
    run["restart_recoverable"] = True
    for step in run.get("steps", []):
        if step.get("status") in {"queued", "running", "cancelling"}:
            step["status"] = "failed"
            step["error"] = message
            step["error_code"] = "INTERRUPTED"
            step["ended_at"] = utc_now()
    return run


def recover_stale_active_runs_for_project(data: dict[str, Any], project_path: str | Path) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    for run in data.get("runs", []):
        if not is_active_run(run):
            continue
        if not (
            _same_path(run.get("original_project_path") or run.get("project_path"), project_path)
            or _same_path(run.get("project_path"), project_path)
        ):
            continue
        if active_run_owner_is_live(run):
            continue
        recovered.append(dict(mark_stale_active_run_interrupted(run)))
    return recovered


def build_project_lock(run: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema": "aiwf.project-run-lock.v1",
        "run_id": run.get("id"),
        "session_id": run.get("session_id"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "project_path": run_project_path(run),
        "effective_project_path": run.get("project_path"),
        "owner": current_run_owner(),
        "created_at": run.get("created_at") or now,
        "updated_at": now,
    }


def read_project_lock(project_path: str | Path) -> dict[str, Any] | None:
    path = project_lock_path(project_path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "aiwf.project-run-lock.v1", "invalid": True, "path": str(path)}
    return raw if isinstance(raw, dict) else {"schema": "aiwf.project-run-lock.v1", "invalid": True, "path": str(path)}


def write_project_lock(run: dict[str, Any]) -> dict[str, Any]:
    project_path = run_project_path(run)
    if not project_path:
        return {}
    lock = build_project_lock(run)
    path = project_lock_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, json.dumps(lock, indent=2, ensure_ascii=False))
    return lock


def clear_project_lock(run_or_project_path: dict[str, Any] | str | Path, *, run_id: str | None = None) -> bool:
    if isinstance(run_or_project_path, dict):
        project_path = run_project_path(run_or_project_path)
        expected_run_id = run_id or run_or_project_path.get("id")
    else:
        project_path = str(run_or_project_path)
        expected_run_id = run_id
    if not project_path:
        return False
    path = project_lock_path(project_path)
    if not path.exists():
        return False
    lock = read_project_lock(project_path) or {}
    if expected_run_id and lock.get("run_id") not in {None, expected_run_id}:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def find_active_run_for_project(data: dict[str, Any], project_path: str | Path, *, exclude_run_id: str | None = None) -> dict[str, Any] | None:
    for run in data.get("runs", []):
        if exclude_run_id and run.get("id") == exclude_run_id:
            continue
        if not is_active_run(run):
            continue
        if _same_path(run.get("original_project_path") or run.get("project_path"), project_path) or _same_path(run.get("project_path"), project_path):
            if active_run_owner_is_live(run):
                return run
    return None


def cleanup_stale_project_lock(project_path: str | Path, data: dict[str, Any]) -> dict[str, Any]:
    lock = read_project_lock(project_path)
    if not lock:
        return {"removed": False, "reason": "no_lock"}
    if lock.get("invalid"):
        clear_project_lock(project_path)
        return {"removed": True, "reason": "invalid_lock", "lock": lock}
    lock_run_id = lock.get("run_id")
    run = next((item for item in data.get("runs", []) if item.get("id") == lock_run_id), None)
    if run and is_active_run(run) and active_run_owner_is_live(run):
        return {"removed": False, "reason": "active_run", "lock": lock}
    owner = lock.get("owner") or {}
    if owner and not owner_matches_current_process(owner) and owner_process_is_alive(owner):
        return {"removed": False, "reason": "live_foreign_owner", "lock": lock}
    removed = clear_project_lock(project_path, run_id=lock_run_id)
    return {"removed": removed, "reason": "stale_lock", "lock": lock}


def mark_cancel_requested(run: dict[str, Any], *, reason: str = "Workflow cancellation requested by user.") -> None:
    run["cancel_requested"] = True
    run["cancel_reason"] = reason
    run["cancel_requested_at"] = utc_now()
    run["status"] = "cancelling"
    run["updated_at"] = utc_now()


def cancel_requested(run: dict[str, Any]) -> bool:
    return bool(run.get("cancel_requested") or run.get("status") == "cancelling")


def mark_interrupted_store_runs(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Mark stale queued/running runs owned by this process as failed after restart.

    Returns changed runs so callers can mirror state files and write logs.
    """
    owner = current_run_owner()
    changed: list[dict[str, Any]] = []
    for run in data.get("runs", []):
        if run.get("status") not in {"queued", "running", "cancelling"}:
            continue
        run_owner = run.get("run_owner")
        if run_owner and not owner_matches_current_process(run_owner) and owner_process_is_alive(run_owner):
            continue
        run["status"] = "failed"
        run["error"] = "Workflow server restarted before this run completed. Resume or retry the run after reviewing artifacts."
        run["error_code"] = "INTERRUPTED"
        run["ended_at"] = utc_now()
        run["updated_at"] = utc_now()
        run["interrupted_by_owner"] = owner
        run["restart_recoverable"] = True
        for step in run.get("steps", []):
            if step.get("status") == "running":
                step["status"] = "failed"
                step["error"] = run["error"]
                step["error_code"] = "INTERRUPTED"
                step["ended_at"] = utc_now()
        changed.append(run)
    return changed


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "recover_stale_active_runs_for_project",
    "mark_stale_active_run_interrupted",
    "active_run_owner_is_live",
    "TERMINAL_RUN_STATUSES",
    "cancel_requested",
    "cleanup_stale_project_lock",
    "clear_project_lock",
    "find_active_run_for_project",
    "is_active_run",
    "mark_cancel_requested",
    "mark_interrupted_store_runs",
    "project_lock_path",
    "read_project_lock",
    "run_project_path",
    "write_project_lock",
]
