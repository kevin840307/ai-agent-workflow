from __future__ import annotations

from copy import deepcopy
from typing import Any

from .thinking import apply_thinking_level_to_steps

VALID_RUN_PROFILES = {"small", "normal", "strong", "deep", "strict", "debug"}
LEGACY_PROFILE_ALIASES = {
    "fast": "small",
    "quick": "small",
    "low": "small",
    "small-model": "small",
    "normal-model": "normal",
    "high": "deep",
    "strict-model": "strict",
    "debug-model": "debug",
    "最高": "deep",
    "超高": "deep",
    "deep-thinking": "deep",
    "strong-model": "strong",
}


def normalize_run_profile(value: str | None) -> str:
    profile = str(value or "normal").strip().lower()
    profile = LEGACY_PROFILE_ALIASES.get(profile, profile)
    return profile if profile in VALID_RUN_PROFILES else "normal"


def apply_run_profile(steps: list[dict[str, Any]], profile: str | None) -> list[dict[str, Any]]:
    """Apply model capability profile to workflow metadata only.

    Profiles do not add domain logic and never generate tasks/code.
    - small: shorter prompts, conservative retries, no extra thinking blocks.
    - normal: workflow defaults.
    - strict: caps normal development retries around 10 for stable repair loops.
    - debug: allows high retry ceilings for local troubleshooting only.
    - strong/deep: allows deeper self-checking and higher retry ceilings.
    """
    normalized = normalize_run_profile(profile)
    next_steps = deepcopy(steps)
    if normalized == "normal":
        return next_steps

    small_retry_caps = {
        "generate_task_prompts": 3,
        "plan_tasks": 3,
        "auto_generation": 6,
        "build": 6,
        "generate_tests": 3,
        "implementation_review": 3,
        "ai_review": 3,
    }
    strict_retry_caps = {
        "generate_task_prompts": 10,
        "plan_tasks": 10,
        "auto_generation": 10,
        "build": 10,
        "generate_tests": 10,
        "implementation_review": 10,
        "ai_review": 10,
        "run_test": 10,
        "run_external_validation": 10,
        "final_review": 10,
        "final_gate": 10,
    }
    strong_retry_floors = {
        "generate_task_prompts": 6,
        "plan_tasks": 6,
        "auto_generation": 12,
        "build": 12,
        "generate_tests": 6,
        "implementation_review": 6,
        "ai_review": 6,
        "run_test": 99,
        "run_external_validation": 99,
    }

    debug_retry_floor = 99

    for step in next_steps:
        key = str(step.get("key") or "")
        step_config = step.setdefault("config", {})
        if normalized == "small":
            if key in small_retry_caps:
                current = int(step.get("max_retries", step.get("maxRetries", small_retry_caps[key])) or small_retry_caps[key])
                _set_retry(step, min(current, small_retry_caps[key]))
            step["thinking"] = False
            step["thinkingLevel"] = "none"
            step_config["thinking"] = False
            step_config["thinkingLevel"] = "none"
            step_config["compactPrompt"] = True
            step_config["includeSkillContext"] = False
        elif normalized == "strict":
            if key in strict_retry_caps:
                current = int(step.get("max_retries", step.get("maxRetries", strict_retry_caps[key])) or strict_retry_caps[key])
                _set_retry(step, min(max(current, 1), strict_retry_caps[key]))
            if step.get("type") in {"ai", "review"} or key in strict_retry_caps:
                step["thinking"] = True
                step["thinkingLevel"] = "medium"
                step_config["thinking"] = True
                step_config["thinkingLevel"] = "medium"
        elif normalized == "debug":
            _set_retry(step, max(int(step.get("max_retries", step.get("maxRetries", 0)) or 0), debug_retry_floor))
            step_config["debugMode"] = True
        elif normalized in {"strong", "deep"}:
            if key in strong_retry_floors:
                current = int(step.get("max_retries", step.get("maxRetries", 0)) or 0)
                _set_retry(step, max(current, strong_retry_floors[key]))
            if step.get("type") in {"ai", "review"} or key in strong_retry_floors:
                step["thinking"] = True
                step["thinkingLevel"] = "high"
                step_config["thinking"] = True
                step_config["thinkingLevel"] = "high"
                agent_options = step_config.setdefault("agentOptions", {})
                if isinstance(agent_options, dict):
                    agent_options["thinking"] = True
                    agent_options["thinkingLevel"] = "high"
    if normalized == "small":
        return apply_thinking_level_to_steps(next_steps, "none")
    return next_steps


def _set_retry(step: dict[str, Any], value: int) -> None:
    value = max(0, int(value))
    step["max_retries"] = value
    step["maxRetries"] = value
    config = step.setdefault("config", {})
    config["maxRetries"] = value
    policy = config.get("retryPolicy")
    if isinstance(policy, dict):
        policy["maxRetries"] = value
