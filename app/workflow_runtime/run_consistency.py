from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now
from app.workflow_runtime.run_lifecycle import (
    ACTIVE_RUN_STATUSES,
    active_run_owner_is_live,
    read_project_lock,
    run_project_path,
)

TERMINAL = {"done", "failed", "cancelled"}


def _load_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _artifact_root(run: dict[str, Any]) -> Path:
    return Path(run.get("workspace") or "") / ".workflow" / "artifacts"


def _event_types(run: dict[str, Any]) -> set[str]:
    events = Path(run.get("workspace") or "") / ".workflow" / "events.jsonl"
    types: set[str] = set()
    if not events.exists():
        return types
    for line in events.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            types.add("__INVALID_JSON__")
            continue
        if isinstance(payload, dict) and payload.get("type"):
            types.add(str(payload["type"]))
    return types


def _status_issue(run: dict[str, Any], issue: str, severity: str = "error", **extra: Any) -> dict[str, Any]:
    return {
        "severity": severity,
        "run_id": run.get("id"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "issue": issue,
        **extra,
    }


def check_run_consistency(run: dict[str, Any], *, project_lock: dict[str, Any] | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    workspace = Path(run.get("workspace") or "")
    wf = workspace / ".workflow"
    status = run.get("status")
    steps = run.get("steps") or []

    if not run.get("id"):
        issues.append(_status_issue(run, "missing_run_id"))
    if not workspace or not workspace.exists():
        issues.append(_status_issue(run, "workspace_missing", workspace=str(workspace)))
    state = _load_json(wf / "state.json")
    if state is None:
        issues.append(_status_issue(run, "state_json_missing_or_invalid"))
    elif state.get("status") != status:
        issues.append(_status_issue(run, "state_status_mismatch", store_status=status, state_status=state.get("status")))

    if status in ACTIVE_RUN_STATUSES and not active_run_owner_is_live(run):
        issues.append(_status_issue(run, "active_run_owner_not_live", severity="warning"))
    if status in TERMINAL and not run.get("ended_at"):
        issues.append(_status_issue(run, "terminal_run_missing_ended_at"))
    if status == "done":
        failed_steps = [step.get("key") for step in steps if step.get("status") == "failed"]
        if failed_steps:
            issues.append(_status_issue(run, "done_run_has_failed_steps", failed_steps=failed_steps))
    if status == "failed" and not (run.get("error") or run.get("error_code")):
        issues.append(_status_issue(run, "failed_run_missing_error"))

    event_types = _event_types(run)
    if "__INVALID_JSON__" in event_types:
        issues.append(_status_issue(run, "events_jsonl_contains_invalid_json"))
    if not event_types:
        issues.append(_status_issue(run, "events_jsonl_missing_or_empty", severity="warning"))
    if status in TERMINAL and not any(t in event_types for t in {"run.completed", "run.failed", "run.cancelled", f"run.{status}"}):
        issues.append(_status_issue(run, "terminal_event_missing", severity="warning", event_types=sorted(event_types)))

    artifact_index = _artifact_root(run) / "index.json"
    if not artifact_index.exists():
        issues.append(_status_issue(run, "artifact_index_missing", severity="warning"))
    else:
        index = _load_json(artifact_index)
        if not isinstance(index, dict):
            issues.append(_status_issue(run, "artifact_index_invalid"))
        else:
            for record in index.get("records") or []:
                rel = record.get("path")
                if rel and not (_artifact_root(run) / rel).exists():
                    issues.append(_status_issue(run, "artifact_record_target_missing", severity="warning", artifact=rel))

    if status == "done" and not (_artifact_root(run) / "reports" / "final-report.md").exists():
        issues.append(_status_issue(run, "done_run_missing_final_report", severity="warning"))

    if project_lock and project_lock.get("run_id") == run.get("id") and status in TERMINAL:
        issues.append(_status_issue(run, "terminal_run_still_has_project_lock", lock=project_lock))
    return {
        "schema": "aiwf.run-consistency.v1",
        "run_id": run.get("id"),
        "status": "PASS" if not any(i.get("severity") == "error" for i in issues) else "FAIL",
        "checked_at": utc_now(),
        "issue_count": len(issues),
        "error_count": sum(1 for item in issues if item.get("severity") == "error"),
        "warning_count": sum(1 for item in issues if item.get("severity") == "warning"),
        "issues": issues,
    }


def check_store_consistency(data: dict[str, Any]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    lock_by_project: dict[str, dict[str, Any] | None] = {}
    for run in data.get("runs", []):
        project = run_project_path(run)
        lock = None
        if project:
            if project not in lock_by_project:
                lock_by_project[project] = read_project_lock(project)
            lock = lock_by_project.get(project)
        reports.append(check_run_consistency(run, project_lock=lock))
    errors = sum(r.get("error_count", 0) for r in reports)
    warnings = sum(r.get("warning_count", 0) for r in reports)
    return {
        "schema": "aiwf.store-consistency.v1",
        "status": "PASS" if errors == 0 else "FAIL",
        "checked_at": utc_now(),
        "run_count": len(reports),
        "error_count": errors,
        "warning_count": warnings,
        "runs": reports,
    }


def render_consistency_report(report: dict[str, Any]) -> str:
    lines = [
        "# Run Consistency Report",
        "",
        f"- Schema: {report.get('schema')}",
        f"- Status: {report.get('status')}",
        f"- Run Count: {report.get('run_count')}",
        f"- Errors: {report.get('error_count')}",
        f"- Warnings: {report.get('warning_count')}",
        "",
        "## Runs",
    ]
    for run in report.get("runs") or []:
        lines.append(f"- `{run.get('run_id')}`: {run.get('status')} ({run.get('error_count')} errors, {run.get('warning_count')} warnings)")
        for issue in run.get("issues") or []:
            lines.append(f"  - {issue.get('severity', 'error').upper()}: {issue.get('issue')}")
    if not report.get("runs"):
        lines.append("- No runs found.")
    return "\n".join(lines).rstrip() + "\n"
