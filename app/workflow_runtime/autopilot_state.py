from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.core.paths import utc_now


async def set_autopilot_state(
    run_id: str,
    state: str,
    *,
    update_run: Callable[[str, Callable[[dict[str, Any]], Any]], Awaitable[dict[str, Any]]],
    detail: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the unattended state machine without coupling it to UI wording."""
    payload: dict[str, Any] = {}

    def apply(run: dict[str, Any]) -> None:
        nonlocal payload
        row = {
            "state": str(state),
            "detail": detail,
            "at": utc_now(),
            "evidence": dict(evidence or {}),
        }
        history = run.setdefault("autopilot_history", [])
        if not history or history[-1].get("state") != row["state"] or history[-1].get("detail") != row["detail"]:
            history.append(row)
            del history[:-120]
        run["autopilot_state"] = row
        run["updated_at"] = utc_now()
        payload = row

    await update_run(run_id, apply)
    return payload


__all__ = ["set_autopilot_state"]
