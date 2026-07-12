from __future__ import annotations

from copy import deepcopy
from typing import Any

THINKING_LEVELS = ("none", "medium", "high", "extreme")
THINKING_LABELS = {
    "none": "無",
    "medium": "中",
    "high": "高",
    "extreme": "極高",
}

_ALIAS_MAP = {
    "": "none",
    "0": "none",
    "false": "none",
    "off": "none",
    "no": "none",
    "none": "none",
    "null": "none",
    "disabled": "none",
    "無": "none",
    "无": "none",
    "不啟用": "none",
    "不用": "none",
    "1": "medium",
    "true": "medium",
    "on": "medium",
    "yes": "medium",
    "medium": "medium",
    "normal": "medium",
    "default": "medium",
    "中": "medium",
    "中等": "medium",
    "一般": "medium",
    "2": "high",
    "high": "high",
    "deep": "high",
    "高": "high",
    "深": "high",
    "深思": "high",
    "3": "extreme",
    "very_high": "extreme",
    "very-high": "extreme",
    "extreme": "extreme",
    "max": "extreme",
    "最高": "extreme",
    "超高": "extreme",
    "極高": "extreme",
    "极高": "extreme",
}


def normalize_thinking_level(value: Any, default: str = "none") -> str:
    """Normalize user/UI/legacy boolean thinking values to one of four levels."""
    fallback = _ALIAS_MAP.get(str(default or "none").strip().lower(), "none")
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "medium" if value else "none"
    text = str(value).strip()
    lowered = text.lower().replace(" ", "_")
    return _ALIAS_MAP.get(lowered) or _ALIAS_MAP.get(text) or fallback


def thinking_enabled(level: Any) -> bool:
    return normalize_thinking_level(level) != "none"


def thinking_label(level: Any) -> str:
    normalized = normalize_thinking_level(level)
    return THINKING_LABELS[normalized]


def step_thinking_level(step_record: dict[str, Any] | None, run: dict[str, Any] | None = None) -> str:
    """Return the effective thinking level for a step.

    Run-level overrides are applied only when `thinking_level_override` is true so
    API callers that do not send the new field keep legacy step metadata behavior.
    """
    run = run or {}
    if run.get("thinking_level_override"):
        return normalize_thinking_level(run.get("thinking_level"), default="none")

    step_record = step_record or {}
    config = step_record.get("config") if isinstance(step_record.get("config"), dict) else {}
    raw = (
        config.get("thinkingLevel")
        if config.get("thinkingLevel") is not None
        else config.get("thinking_level")
    )
    if raw is None:
        raw = step_record.get("thinkingLevel") if step_record.get("thinkingLevel") is not None else step_record.get("thinking_level")
    if raw is None:
        raw = config.get("thinking") if config.get("thinking") is not None else step_record.get("thinking")
    return normalize_thinking_level(raw, default="none")


def render_thinking_guidance(level: Any, *, step_key: str = "", workflow_id: str = "") -> str:
    normalized = normalize_thinking_level(level)
    if normalized == "none":
        return ""

    # Adaptive Auto Workflow intentionally uses tiny self-check hints only.
    # The controller simulates a human typing concise prompts into Qwen/OpenCode;
    # a long generic Thinking Control block makes small/local models drift into
    # explaining the workflow instead of editing the project.
    if workflow_id == "adaptive-auto-workflow" or step_key in {"generate_task_prompts", "auto_generation", "ai_review"}:
        adaptive_checks = {
            "generate_task_prompts": (
                "Internal check: derive the SPEC only from the user request; output short human CLI task prompts, not shell commands, code, or workflow docs."
            ),
            "auto_generation": (
                "Internal check: directly modify real project files for the current task; keep valid earlier work and add/update tests when needed."
            ),
            "ai_review": (
                "Internal check: compare the project result against every SPEC acceptance item and test/validation expectation before PASS."
            ),
        }
        return adaptive_checks.get(
            step_key,
            "Internal check: satisfy the current SPEC/task with the smallest safe project changes and preserve completed work.",
        ).strip() + "\n"

    label = THINKING_LABELS[normalized]
    lines = [
        "# Thinking Control",
        "",
        f"Thinking Level: {label} ({normalized})",
        "",
        "Before producing the final artifact, internally reason about the task. Do not expose hidden chain-of-thought; output only the requested artifact and short summaries when the step prompt asks for them.",
        "",
        "## Required Internal Checks",
        "- Understand the current step goal, user requirement, allowed output format, and project write boundaries.",
        "- Identify constraints, required files, validation gates, likely failure modes, and safe assumptions.",
        "- Produce the artifact or project edits, then self-check against the validation rules before finishing.",
    ]
    if normalized in {"high", "extreme"}:
        lines.extend([
            "- Create an internal mini-spec for this step: goal, inputs, outputs, acceptance criteria, and retry boundary.",
            "- Prefer the smallest safe change that satisfies the current step; preserve valid previous work.",
            "- If validation feedback exists, diagnose the local root cause first instead of restarting the whole workflow.",
        ])
    if normalized == "extreme":
        lines.extend([
            "- Run an internal Reflect → Decide gate after the step: continue, repair current step, or replan only remaining internal tasks when the current plan is outdated.",
            "- Check edge cases, dependency drift, output handoff to the next step, and whether future internal prompts still match the current result.",
            "- If the plan needs adjustment, keep completed valid work immutable and change only remaining internal task scope.",
        ])
    return "\n".join(lines).strip() + "\n"


def apply_thinking_level_to_steps(steps: list[dict[str, Any]], level: Any) -> list[dict[str, Any]]:
    """Return a deep-copied step list with a run-level thinking override applied."""
    normalized = normalize_thinking_level(level, default="none")
    enabled = thinking_enabled(normalized)
    next_steps = deepcopy(steps)
    for step in next_steps:
        key = str(step.get("key") or "")
        step_type = str(step.get("type") or "")
        config = step.setdefault("config", {})
        if not isinstance(config, dict):
            config = {}
            step["config"] = config
        if step_type in {"ai", "review", "agent", "qwen"} or key in {
            "plan_tasks",
            "generate_task_prompts",
            "auto_generation",
            "ai_review",
            "sub_agent_review",
            "build",
            "generate_tests",
            "final_review",
        }:
            step["thinking"] = enabled
            step["thinkingLevel"] = normalized
            config["thinking"] = enabled
            config["thinkingLevel"] = normalized
            agent_options = config.setdefault("agentOptions", {})
            if isinstance(agent_options, dict):
                agent_options["thinking"] = enabled
                agent_options["thinkingLevel"] = normalized
    return next_steps
