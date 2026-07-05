from __future__ import annotations

from copy import deepcopy
from typing import Any

from .thinking import apply_thinking_level_to_steps

VALID_RUN_PROFILES = {"fast", "normal", "deep"}


def normalize_run_profile(value: str | None) -> str:
    profile = str(value or "normal").strip().lower()
    if profile in {"high", "最高", "超高", "deep-thinking"}:
        return "deep"
    if profile in {"quick", "low"}:
        return "fast"
    return profile if profile in VALID_RUN_PROFILES else "normal"


def apply_run_profile(steps: list[dict[str, Any]], profile: str | None) -> list[dict[str, Any]]:
    """Apply a small, deterministic run profile to workflow step metadata.

    Profiles tune runner behavior only; they do not add domain-specific logic.
    - fast: fewer retries for quick iteration.
    - normal: keep workflow defaults.
    - deep: enable compatible-agent thinking and keep/increase retry budgets.
    """
    normalized = normalize_run_profile(profile)
    next_steps = deepcopy(steps)
    if normalized == "normal":
        return next_steps

    fast_retry_caps = {
        "prepare_project": 1,
        "plan_tasks": 2,
        "build": 4,
        "generate_tests": 2,
    }
    deep_retry_floors = {
        "prepare_project": 3,
        "plan_tasks": 5,
        "build": 12,
        "generate_tests": 5,
        "run_test": 99,
        "run_external_validation": 99,
    }

    for step in next_steps:
        key = str(step.get("key") or "")
        step_config = step.setdefault("config", {})
        if normalized == "fast":
            if key in fast_retry_caps:
                _set_retry(step, min(int(step.get("max_retries", step.get("maxRetries", 0)) or 0), fast_retry_caps[key]))
            step["thinking"] = False
            step_config["thinking"] = False
        elif normalized == "deep":
            if key in deep_retry_floors:
                current = int(step.get("max_retries", step.get("maxRetries", 0)) or 0)
                _set_retry(step, max(current, deep_retry_floors[key]))
            if step.get("type") in {"ai", "review"} or key in {"prepare_project", "plan_tasks", "build", "generate_tests"}:
                step["thinking"] = True
                step["thinkingLevel"] = "high"
                step_config["thinking"] = True
                step_config["thinkingLevel"] = "high"
                agent_options = step_config.setdefault("agentOptions", {})
                if isinstance(agent_options, dict):
                    agent_options["thinking"] = True
                    agent_options["thinkingLevel"] = "high"
    if normalized == "fast":
        return apply_thinking_level_to_steps(next_steps, "none")
    return next_steps


def _set_retry(step: dict[str, Any], value: int) -> None:
    value = max(0, int(value))
    step["max_retries"] = value
    step["maxRetries"] = value
    config = step.setdefault("config", {})
    config["maxRetries"] = value
