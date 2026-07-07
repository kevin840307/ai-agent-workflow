from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text

EVENT_SCHEMA = "aiwf.workflow-events.v1"


def event_log_path(run_or_workspace: dict[str, Any] | str | Path) -> Path:
    if isinstance(run_or_workspace, dict):
        workspace = Path(run_or_workspace.get("workspace") or "")
    else:
        workspace = Path(run_or_workspace)
    return workspace / ".workflow" / "events.jsonl"


def normalize_event(
    event_type: str,
    *,
    run_id: str | None = None,
    step_key: str | None = None,
    message: str = "",
    status: str | None = None,
    error_code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "ts": utc_now(),
        "type": str(event_type or "event"),
    }
    if run_id:
        event["run_id"] = run_id
    if step_key:
        event["step_key"] = step_key
    if status:
        event["status"] = status
    if error_code:
        event["error_code"] = error_code
    if message:
        event["message"] = str(message)
    if extra:
        # Keep the standard keys above authoritative while allowing useful payload.
        for key, value in extra.items():
            if key not in event:
                event[key] = value
    return event


def append_event(run: dict[str, Any], event_type: str, *, step_key: str | None = None, message: str = "", status: str | None = None, error_code: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    path = event_log_path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = normalize_event(
        event_type,
        run_id=str(run.get("id") or ""),
        step_key=step_key,
        message=message,
        status=status,
        error_code=error_code,
        extra=extra,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def read_events(run_or_workspace: dict[str, Any] | str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = event_log_path(run_or_workspace)
    raw = read_text(path)
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = {"schema": EVENT_SCHEMA, "ts": "", "type": "event.parse_failed", "message": line[:500]}
        if isinstance(parsed, dict):
            events.append(parsed)
    return events[-limit:] if limit and limit > 0 else events


def summarize_events(run_or_workspace: dict[str, Any] | str | Path) -> dict[str, Any]:
    events = read_events(run_or_workspace)
    counts: dict[str, int] = {}
    for event in events:
        kind = str(event.get("type") or "event")
        counts[kind] = counts.get(kind, 0) + 1
    return {"schema": EVENT_SCHEMA, "event_count": len(events), "counts": counts, "events": events}
