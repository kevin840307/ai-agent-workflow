from __future__ import annotations

from pathlib import Path
from typing import Any

from app.workflow_engine.state_machine import derive_current_action, friendly_step_title, phase_for_step, current_step
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.run_diff import build_run_diff
from app.workflow_runtime.stability_score import compute_workflow_stability_score
from app.workflow_runtime.artifact_policy import filter_artifacts
from app.workflow_runtime.recovery_counters import public_recovery_counters
from app.workflow_runtime.scope_control import analyze_scope_delta
from app.core.paths import read_text

ACTIVE = {"queued", "running", "waiting_input", "cancelling"}


def _normalized_change_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    # Windows paths are case-insensitive and users should never see controller
    # projection aliases such as ``project\sorts.py`` and ``./sorts.py`` as two
    # separate changes.
    return "/".join(part for part in path.split("/") if part not in {"", "."})


def _dedupe_changed_files(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate file rows using Windows-safe path identity.

    Diff projection, checkpoint ownership and legacy run state can all mention
    the same file.  The user-facing overview must present one authoritative row
    and must never sum duplicate line counts.
    """
    ordered: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for raw in items:
        item = dict(raw or {})
        path = _normalized_change_path(item.get("path"))
        if not path:
            continue
        item["path"] = path
        item["added"] = int(item.get("added") or item.get("added_lines") or item.get("additions") or 0)
        item["removed"] = int(item.get("removed") or item.get("deleted_lines") or item.get("deletions") or 0)
        key = path.casefold()
        if key not in positions:
            positions[key] = len(ordered)
            ordered.append(item)
            continue
        current = ordered[positions[key]]
        # Duplicate projections describe the same patch; use the strongest
        # available values rather than adding them and inflating +/-.
        current["added"] = max(int(current.get("added") or 0), int(item.get("added") or 0))
        current["removed"] = max(int(current.get("removed") or 0), int(item.get("removed") or 0))
        if current.get("status") in {None, "modified"} and item.get("status"):
            current["status"] = item.get("status")
        if not current.get("ownership") and item.get("ownership"):
            current["ownership"] = item.get("ownership")
    return ordered


def _validation_status(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in run.get("steps") or []:
        key = str(step.get("key") or "").lower()
        if not any(token in key for token in ("test", "validation", "review", "gate")):
            continue
        status = str(step.get("status") or "pending")
        label = friendly_step_title(step)
        rows.append(
            {
                "key": step.get("key"),
                "label": label,
                "status": status,
                "error": step.get("error"),
                "error_code": step.get("error_code"),
                "retry_count": int(step.get("retry_count") or 0),
            }
        )
    return rows


def _recommended_actions(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Return at most two user-facing actions.

    Technical actions remain available in the diagnostics drawer. The primary
    Run Center should never look like an operator console.
    """
    status = str(run.get("status") or "")
    approval = str(run.get("approval_state") or "not_required")
    patch_mode = str(run.get("patch_mode") or "auto_apply")
    actions: list[dict[str, Any]] = []
    if status == "waiting_input":
        return [{"id": "answer", "label": "提供資訊", "kind": "primary"}]
    if status == "failed":
        failure = classify_failure(run.get("error"), error_code=run.get("error_code"))
        if run.get("restart_recoverable") and isinstance(run.get("recovery"), dict):
            actions.append({"id": "resume", "label": "從 Checkpoint 繼續", "kind": "primary"})
        elif failure.get("code") in {"TIMEOUT", "SESSION_NOT_FOUND", "SESSION_ALREADY_EXISTS", "CONTEXT_LIMIT_REACHED"}:
            actions.append({"id": "retry_fresh_session", "label": "使用新 Session 重試", "kind": "primary"})
        else:
            actions.append({"id": "retry_current", "label": "重試目前步驟", "kind": "primary"})
        actions.append({"id": "keep_changes", "label": "保留目前變更", "kind": "secondary"})
        return actions
    if status == "done":
        if patch_mode in {"review", "dry_run"} and approval == "pending":
            return [
                {"id": "approve", "label": "核准並檢視 Patch", "kind": "primary"},
                {"id": "reject", "label": "拒絕這次變更", "kind": "danger"},
            ]
        return [
            {"id": "view_changes", "label": "查看變更", "kind": "primary"},
            {"id": "run_again", "label": "再次執行", "kind": "secondary"},
        ]
    if status in ACTIVE:
        return [{"id": "stop", "label": "停止執行", "kind": "danger"}]
    return actions


def _file_ownership(run: dict[str, Any], changed_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    owners: dict[str, dict[str, Any]] = {}
    for step in run.get("steps") or []:
        for raw in step.get("changed_files") or []:
            path = str(raw.get("path") if isinstance(raw, dict) else raw).replace("\\", "/")
            if path:
                owners[path] = {"source": step.get("key"), "task_id": None, "reason": "step change"}
    for checkpoint in run.get("task_checkpoints") or []:
        for path in checkpoint.get("changed_files") or []:
            owners[str(path).replace("\\", "/")] = {
                "source": checkpoint.get("step_key"),
                "task_id": checkpoint.get("task_id"),
                "checkpoint_id": checkpoint.get("id"),
                "reason": "accepted task checkpoint",
            }
    result = []
    for item in changed_files:
        path = str(item.get("path") or "").replace("\\", "/")
        result.append({**item, "ownership": owners.get(path) or {"source": "workflow", "reason": "run diff"}})
    return result


def _human_retry(run: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
    counters = public_recovery_counters(run)
    failure = classify_failure((current or {}).get("error") or run.get("error"), error_code=(current or {}).get("error_code") or run.get("error_code"))
    return {
        "attempt": max(0, int((current or {}).get("retry_count") or 0)),
        "reason": failure.get("user_message") or failure.get("title") or "No active repair",
        "strategy": failure.get("recommended_action") or "Continue from the latest accepted checkpoint.",
        "counters": counters,
    }


def build_run_overview(run: dict[str, Any]) -> dict[str, Any]:
    steps = list(run.get("steps") or [])
    total = len(steps)
    completed = sum(1 for step in steps if step.get("status") in {"passed", "skipped"})
    failed = next((step for step in steps if step.get("status") in {"failed", "waiting_input", "cancelled"}), None)
    retries = sum(int(step.get("retry_count") or 0) for step in steps)
    action = derive_current_action(run)
    run_dir = Path(str(run.get("workspace") or ""))
    try:
        diff = build_run_diff(run, run_dir) if run_dir.exists() else {"files": [], "summary": {}}
    except Exception:
        diff = {"files": [], "summary": {}}
    files = diff.get("files") or diff.get("changes") or []
    changed_files = []
    for item in files[:100]:
        if isinstance(item, str):
            changed_files.append({"path": item, "status": "modified"})
        else:
            changed_files.append(
                {
                    "path": item.get("path") or item.get("file"),
                    "status": item.get("status") or item.get("change") or "modified",
                    "added": item.get("added") or item.get("additions") or 0,
                    "removed": item.get("removed") or item.get("deletions") or 0,
                }
            )
    changed_files = _dedupe_changed_files(_file_ownership(run, changed_files))
    requirement = read_text(run_dir / "requirement.md") if run_dir.exists() else ""
    scope_delta = analyze_scope_delta(requirement, file_changes=changed_files, planned_tasks=list(run.get("tasks") or []))
    validation = _validation_status(run)
    validation_passed = bool(validation) and all(row["status"] in {"passed", "skipped"} for row in validation)
    stability = compute_workflow_stability_score(
        run,
        {
            "workflow_validation_has_pass": validation_passed or not validation,
            "manual_validation_returncode": 0 if validation_passed or not validation else 1,
        },
    )
    current = current_step(run)
    return {
        "schema": "aiwf.run-overview.v1",
        "run_id": run.get("id"),
        "status": run.get("status"),
        "phase": phase_for_step(current, run.get("status")),
        "workflow": run.get("workflow_name") or run.get("workflow_id"),
        "project_path": run.get("original_project_path") or run.get("project_path"),
        "effective_project_path": run.get("project_path"),
        "current_action": action,
        "progress": {"completed": completed, "total": total, "percent": round((completed / total) * 100) if total else 0},
        "summary": {
            "steps_passed": sum(1 for step in steps if step.get("status") == "passed"),
            "steps_total": total,
            "retry_total": retries,
            "changed_file_count": len(changed_files),
            "validation_passed": validation_passed,
            "risk": (run.get("risk_assessment") or {}).get("level") or stability.get("risk"),
            "quality_score": stability.get("score"),
            "scope_status": scope_delta.get("status"),
            "recovery": public_recovery_counters(run),
        },
        "steps": [
            {
                "key": step.get("key"),
                "label": friendly_step_title(step),
                "status": step.get("status"),
                "retry_count": int(step.get("retry_count") or 0),
                "error": step.get("error"),
                "error_code": step.get("error_code"),
                "started_at": step.get("started_at"),
                "ended_at": step.get("ended_at"),
            }
            for step in steps
        ],
        "changes": {"files": changed_files, "summary": diff.get("summary") or {}},
        "validation": validation,
        "scope_delta": scope_delta,
        "risk_assessment": run.get("risk_assessment") or {},
        "model_capability": run.get("model_capability") or {},
        "validator_plans": run.get("validator_plans") or [],
        "task_checkpoints": list(run.get("task_checkpoints") or [])[-20:],
        "timeline": list(run.get("timeline") or [])[-100:],
        "retry_explanation": _human_retry(run, current),
        "approval": {"mode": run.get("approval_mode") or "fully_automatic", "state": run.get("approval_state") or "not_required"},
        "error": {
            "message": run.get("error") or (failed or {}).get("error"),
            "code": run.get("error_code") or (failed or {}).get("error_code"),
            "classification": classify_failure(run.get("error") or (failed or {}).get("error"), error_code=run.get("error_code") or (failed or {}).get("error_code")) if (run.get("error") or failed) else None,
        },
        "recommended_actions": _recommended_actions(run),
        "restart_recoverable": bool(run.get("restart_recoverable")),
        "recovery": run.get("recovery") if run.get("restart_recoverable") else None,
        "last_checkpoint_id": run.get("last_checkpoint_id"),
        "essential_artifacts": filter_artifacts(run.get("artifacts") or [], "essential")[:12],
        "advanced": {
            "patch_mode": run.get("patch_mode"),
            "patch_status": run.get("patch_status"),
            "agent": run.get("agent"),
            "session_ids": run.get("agent_session_ids") or {},
            "workspace": run.get("workspace"),
        },
    }


__all__ = ["build_run_overview"]
