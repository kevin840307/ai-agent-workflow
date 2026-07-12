from __future__ import annotations

from typing import Any

# Exact executable step kinds are protocol metadata, not natural-language intent.
_PHASE_BY_KIND = {
    "python_context": "planning",
    "agent_plan": "planning",
    "agent_build": "executing",
    "agent_generate_tests": "executing",
    "python_task_verifier": "validating",
    "repair_loop": "executing",
    "assembly_verifier": "validating",
    "external_acceptance_python": "validating",
    "evidence_verifier": "validating",
    "diff_reviewer_agent": "reviewing",
    "final_gate": "validating",
}
_ROLE_BY_PHASE = {
    "planning": "planning",
    "executing": "build",
    "validating": "validation",
    "reviewing": "review",
    "finalizing": "review",
}


def _config(step: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(step or {})
    nested = item.get("config")
    if isinstance(nested, dict):
        item.update(nested)
    contract = item.get("contract")
    if isinstance(contract, dict):
        item.update({key: value for key, value in contract.items() if key not in item})
    return item


def step_phase(step: dict[str, Any] | None, default: str = "executing") -> str:
    item = _config(step)
    explicit = item.get("phase") or item.get("workflowPhase") or item.get("workflow_phase")
    if explicit:
        return str(explicit).strip().lower()
    kind = str(item.get("type") or item.get("kind") or item.get("action") or "").strip().lower()
    return _PHASE_BY_KIND.get(kind, default)


def step_session_role(step: dict[str, Any] | None, default: str = "build") -> str:
    item = _config(step)
    explicit = item.get("sessionRole") or item.get("session_role") or item.get("role")
    if explicit:
        return str(explicit).strip().lower()
    return _ROLE_BY_PHASE.get(step_phase(item), default)


def step_evidence_category(step: dict[str, Any] | None) -> str | None:
    item = _config(step)
    explicit = item.get("evidenceCategory") or item.get("evidence_category")
    if explicit:
        return str(explicit).strip().lower()
    if step_phase(item) == "validating":
        return "validation"
    return None


def is_validation_step(step: dict[str, Any] | None) -> bool:
    return step_evidence_category(step) == "validation"


__all__ = ["is_validation_step", "step_evidence_category", "step_phase", "step_session_role"]
