from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.workflow_runtime.failure_classifier import classify_step_failure, classify_failure
from app.workflow_runtime.recovery_counters import public_recovery_counters


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration_seconds(start: Any, end: Any) -> float | None:
    started = _parse_time(start)
    ended = _parse_time(end)
    if not started:
        return None
    if not ended:
        ended = datetime.now(timezone.utc)
    return max(0.0, round((ended - started).total_seconds(), 3))


def build_run_console(run: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, UI-friendly run console/timeline view.

    This intentionally duplicates key fields from the run state so the UI does
    not need to understand raw state.json internals. It is deterministic and can
    also be stored in exported run bundles.
    """
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(run.get("steps") or []):
        failure = None
        if step.get("error") or step.get("status") in {"failed", "waiting_input", "cancelled"}:
            failure = classify_step_failure(step)
        events = step.get("events") or []
        steps.append(
            {
                "index": index,
                "key": step.get("key"),
                "title": step.get("title") or step.get("name") or step.get("key"),
                "status": step.get("status"),
                "retry_count": int(step.get("retry_count") or 0),
                "started_at": step.get("started_at"),
                "ended_at": step.get("ended_at"),
                "duration_sec": _duration_seconds(step.get("started_at"), step.get("ended_at")),
                "error": step.get("error"),
                "error_code": step.get("error_code"),
                "failure": failure,
                "changed_files": step.get("changed_files") or [],
                "event_count": len(events),
                "recent_events": events[-8:],
            }
        )

    timeline = []
    for event in run.get("timeline") or []:
        timeline.append(
            {
                "at": event.get("at") or event.get("time") or event.get("timestamp"),
                "step_key": event.get("step_key") or event.get("stepKey") or event.get("step"),
                "kind": event.get("kind") or event.get("type") or "event",
                "message": event.get("message") or "",
            }
        )
    timeline.sort(key=lambda item: item.get("at") or "")

    passed = sum(1 for step in steps if step.get("status") == "passed")
    failed = [step for step in steps if step.get("status") in {"failed", "waiting_input", "cancelled"}]
    retry_total = sum(int(step.get("retry_count") or 0) for step in steps)
    return {
        "schema": "aiwf.run-console.v1",
        "run_id": run.get("id"),
        "session_id": run.get("session_id"),
        "status": run.get("status"),
        "workflow_id": run.get("workflow_id"),
        "workflow_name": run.get("workflow_name"),
        "project_path": run.get("project_path"),
        "original_project_path": run.get("original_project_path"),
        "patch_mode": run.get("patch_mode") or "auto_apply",
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "duration_sec": _duration_seconds(run.get("started_at") or run.get("created_at"), run.get("ended_at")),
        "summary": {
            "steps_total": len(steps),
            "steps_passed": passed,
            "steps_attention": len(failed),
            "retry_total": retry_total,
            "failure_codes": sorted({(step.get("failure") or {}).get("code") for step in failed if step.get("failure")}),
            "recovery": public_recovery_counters(run),
        },
        "run_failure": classify_failure(run.get("error"), error_code=run.get("error_code")) if run.get("error") else None,
        "steps": steps,
        "timeline": timeline,
    }


__all__ = ["build_run_console"]
