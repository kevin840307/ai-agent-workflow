from __future__ import annotations

from typing import Any


def step_kind_from_type(step_type: str) -> str:
    """Normalize UI/workflow step type into runtime kind.

    Backward compatibility:
    - old ``ai`` / ``review`` / ``qwen`` steps now become provider-neutral
      ``agent`` steps.
    - validator/gate/python keep their dedicated runtime semantics.
    """
    return {
        "ai": "agent",
        "qwen": "agent",
        "review": "agent",
        "agent": "agent",
        "validation": "validator",
        "validator": "validator",
        "python": "python",
        "test": "python",
        "gate": "gate",
        "manual": "manual",
    }.get(step_type, step_type or "agent")


def initial_steps(workflow_steps: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if workflow_steps is None:
        workflow_steps = []
    steps: list[dict[str, Any]] = []
    for index, workflow_step in enumerate(workflow_steps):
        if workflow_step.get("enabled") is False:
            continue
        step_type = workflow_step.get("type") or workflow_step.get("kind") or "ai"
        key = workflow_step.get("key") or f"step_{index + 1}"
        steps.append(
            {
                "key": key,
                "title": workflow_step.get("name") or workflow_step.get("title") or key,
                "kind": step_kind_from_type(step_type),
                "type": step_type,
                "agent": workflow_step.get("agent") or workflow_step.get("provider") or "",
                "status": "pending",
                "started_at": None,
                "ended_at": None,
                "error": None,
                "error_code": None,
                "retry_count": 0,
                "config": workflow_step,
                "max_retries": int(workflow_step.get("maxRetries", 2) or 0),
                "retry_from_step_key": workflow_step.get("retryFromStepKey") or "",
                "fail_action": workflow_step.get("failAction") or "same_step",
                "allow_interaction": bool(workflow_step.get("allowInteraction")),
                "thinking": bool(workflow_step.get("thinking")),
                "pause_after_step": bool(workflow_step.get("pauseAfterStep")),
            }
        )
    return steps
