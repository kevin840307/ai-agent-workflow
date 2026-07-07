from __future__ import annotations

from typing import Any


def is_auto_development_workflow(run: dict[str, Any]) -> bool:
    return str(run.get("workflow_id") or "") in {"general-auto-development", "adaptive-auto-workflow"}


def is_general_auto_development_workflow(run: dict[str, Any]) -> bool:
    return str(run.get("workflow_id") or "") == "general-auto-development"


def is_adaptive_workflow(run: dict[str, Any]) -> bool:
    return str(run.get("workflow_id") or "") == "adaptive-auto-workflow"


def config_for_step(run: dict[str, Any], step_key: str) -> dict[str, Any]:
    for step in run.get("steps", []):
        if step.get("key") == step_key:
            config = step.get("config") or {}
            return {**step, **config}
    return {}


def fresh_session_for_step(run: dict[str, Any], step_key: str, *, default_keep_same_session: bool = True) -> bool:
    config = config_for_step(run, step_key)
    return not bool(config.get("keepSameSession", default_keep_same_session))
