from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.paths import DATA_DIR, atomic_write_text, utc_now

_CAPABILITY_DIR = DATA_DIR / "capabilities"


def _safe_agent(agent_name: str | None) -> str:
    value = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(agent_name or "qwen").lower())
    return value.strip("-") or "qwen"


def _key(agent_name: str, model_name: str | None) -> str:
    digest = hashlib.sha256(f"{agent_name}|{model_name or 'unknown'}".encode("utf-8")).hexdigest()[:16]
    return f"{_safe_agent(agent_name)}-{digest}"


def derive_capability_calibration(
    *,
    agent_name: str,
    model_name: str | None,
    context_window: int | str | None,
    steps: list[dict[str, Any]],
    duration_sec: float | None,
) -> dict[str, Any]:
    statuses = {str(item.get("id") or ""): str(item.get("status") or "") for item in steps}
    response_ok = statuses.get("model_response") == "passed"
    session_ok = statuses.get("session_create") == "passed"
    tool_ok = statuses.get("tool_write") == "passed"
    try:
        window = int(context_window or 0)
    except (TypeError, ValueError):
        window = 0

    if not (response_ok and session_ok and tool_ok) or (window and window <= 32768):
        profile = "small"
    elif window >= 98304:
        profile = "strong"
    else:
        profile = "normal"

    profile_limits = {
        "small": {"max_files_per_task": 4, "prompt_budget_chars": 12000, "preferred_workflow": "general-auto-development"},
        "normal": {"max_files_per_task": 10, "prompt_budget_chars": 32000, "preferred_workflow": "general-auto-development"},
        "strong": {"max_files_per_task": 20, "prompt_budget_chars": 70000, "preferred_workflow": "adaptive-auto-workflow"},
    }[profile]
    if window > 0:
        # Keep prompts below roughly half of the model context after allowing
        # room for agent instructions, tool calls, and output tokens.
        profile_limits["prompt_budget_chars"] = min(
            int(profile_limits["prompt_budget_chars"]),
            max(8000, int(window * 0.45 * 3.5)),
        )

    return {
        "schema": "aiwf.capability-calibration.v1",
        "agent": _safe_agent(agent_name),
        "model": model_name or None,
        "context_window": window or None,
        "measured_at": utc_now(),
        "duration_sec": round(float(duration_sec or 0.0), 3),
        "checks": {
            "model_response": response_ok,
            "session_create": session_ok,
            "tool_write": tool_ok,
        },
        "recommended_profile": profile,
        "ready_for_workflow": bool(response_ok and session_ok and tool_ok),
        **profile_limits,
        "sample_count": 1,
    }


def save_capability_calibration(calibration: dict[str, Any]) -> Path:
    _CAPABILITY_DIR.mkdir(parents=True, exist_ok=True)
    agent = _safe_agent(str(calibration.get("agent") or "qwen"))
    model = str(calibration.get("model") or "") or None
    target = _CAPABILITY_DIR / f"{_key(agent, model)}.json"
    atomic_write_text(target, json.dumps(calibration, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(_CAPABILITY_DIR / f"latest-{agent}.json", json.dumps(calibration, indent=2, ensure_ascii=False) + "\n")
    return target


def load_capability_calibration(agent_name: str | None) -> dict[str, Any] | None:
    path = _CAPABILITY_DIR / f"latest-{_safe_agent(agent_name)}.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def apply_capability_calibration(capability: dict[str, Any], calibration: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(capability)
    if not calibration:
        result["calibration_status"] = "not_run"
        return result
    result["calibration_status"] = "ready" if calibration.get("ready_for_workflow") else "blocked"
    result["calibration"] = calibration
    if calibration.get("context_window"):
        result["context_window"] = int(calibration["context_window"])
        result["context_window_source"] = "setup_smoke_calibration"
    # Calibration only tightens the selected profile. It never silently grants
    # a model more work than the explicit profile allows after one smoke test.
    if calibration.get("max_files_per_task"):
        result["max_files_per_task"] = min(int(result.get("max_files_per_task") or 1), int(calibration["max_files_per_task"]))
    if calibration.get("prompt_budget_chars"):
        result["prompt_budget_chars"] = min(int(result.get("prompt_budget_chars") or 8000), int(calibration["prompt_budget_chars"]))
    result["calibrated_preferred_workflow"] = calibration.get("preferred_workflow")
    return result


__all__ = [
    "apply_capability_calibration",
    "derive_capability_calibration",
    "load_capability_calibration",
    "save_capability_calibration",
]
