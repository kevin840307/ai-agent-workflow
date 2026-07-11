from __future__ import annotations

from copy import deepcopy
from typing import Any

MODEL_CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "small": {
        "label": "Small local model",
        "context_window": 32768,
        "tool_calling": "limited",
        "structured_output": "limited",
        "coding_level": "small",
        "max_task_profile": "tiny",
        "max_files_per_task": 4,
        "prompt_budget_chars": 12000,
        "compact_prompt": True,
        "preferred_workflow": "general-auto-development",
        "review_mode": "deterministic_first",
    },
    "normal": {
        "label": "Balanced coding model",
        "context_window": 65536,
        "tool_calling": "reliable",
        "structured_output": "medium",
        "coding_level": "medium",
        "max_task_profile": "standard",
        "max_files_per_task": 12,
        "prompt_budget_chars": 35000,
        "compact_prompt": True,
        "preferred_workflow": "general-auto-development",
        "review_mode": "fresh_read_only",
    },
    "strong": {
        "label": "Strong reasoning/coding model",
        "context_window": 131072,
        "tool_calling": "reliable",
        "structured_output": "reliable",
        "coding_level": "strong",
        "max_task_profile": "complex",
        "max_files_per_task": 30,
        "prompt_budget_chars": 80000,
        "compact_prompt": False,
        "preferred_workflow": "adaptive-auto-workflow",
        "review_mode": "fresh_read_only",
    },
}


def resolve_model_capability(profile: str | None, *, context_window: int | None = None) -> dict[str, Any]:
    key = str(profile or "normal").strip().lower()
    if key not in MODEL_CAPABILITY_PROFILES:
        key = "normal"
    result = deepcopy(MODEL_CAPABILITY_PROFILES[key])
    result["id"] = key
    if context_window and int(context_window) > 0:
        result["context_window"] = int(context_window)
        result["context_window_source"] = "configured"
    else:
        result["context_window_source"] = "profile_default"
    return result


def prompt_limits_for(profile: str | None, *, context_window: int | None = None) -> dict[str, int]:
    capability = resolve_model_capability(profile, context_window=context_window)
    window = int(capability["context_window"])
    return {
        "context_window": window,
        "warn_tokens": int(window * 0.60),
        "handoff_tokens": int(window * 0.75),
        "hard_tokens": int(window * 0.90),
        "prompt_budget_chars": int(capability["prompt_budget_chars"]),
    }


__all__ = ["MODEL_CAPABILITY_PROFILES", "prompt_limits_for", "resolve_model_capability"]
