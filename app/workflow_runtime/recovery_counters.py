from __future__ import annotations

from typing import Any

_COUNTER_KEYS = (
    "agent_attempts",
    "deterministic_repairs",
    "session_restarts",
    "replans",
    "manual_actions",
    "consecutive_failures",
)


def ensure_recovery_counters(run: dict[str, Any]) -> dict[str, int]:
    raw = run.setdefault("recovery_counters", {})
    if not isinstance(raw, dict):
        raw = {}
        run["recovery_counters"] = raw
    for key in _COUNTER_KEYS:
        try:
            raw[key] = max(0, int(raw.get(key) or 0))
        except (TypeError, ValueError):
            raw[key] = 0
    return raw


def increment_recovery_counter(run: dict[str, Any], key: str, amount: int = 1) -> int:
    counters = ensure_recovery_counters(run)
    if key not in counters:
        counters[key] = 0
    counters[key] = max(0, int(counters.get(key) or 0) + int(amount))
    return counters[key]


def reset_consecutive_failures(run: dict[str, Any]) -> None:
    ensure_recovery_counters(run)["consecutive_failures"] = 0


def public_recovery_counters(run: dict[str, Any]) -> dict[str, int]:
    counters = ensure_recovery_counters(run)
    return {key: int(counters.get(key) or 0) for key in _COUNTER_KEYS}


__all__ = [
    "ensure_recovery_counters",
    "increment_recovery_counter",
    "reset_consecutive_failures",
    "public_recovery_counters",
]
