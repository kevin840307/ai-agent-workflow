from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StepContract:
    key: str
    type: str = "ai"
    prompt: str | None = None
    artifact: str | None = None
    functions: list[str] = field(default_factory=list)
    expected_files: list[str] = field(default_factory=list)
    retry_target: str | None = None
    ai_decision_allowed: bool = True
    deterministic_validation: bool = False


@dataclass(slots=True)
class WorkflowContract:
    id: str
    version: str = "v1"
    steps: list[StepContract] = field(default_factory=list)


def normalize_step_contract(step: dict[str, Any]) -> StepContract:
    config = {**step, **(step.get("config") or {})}
    functions = config.get("functions") or config.get("function") or []
    if isinstance(functions, str):
        functions = [item.strip() for item in functions.split(",") if item.strip()]
    return StepContract(
        key=str(config.get("key") or config.get("id") or ""),
        type=str(config.get("type") or "ai"),
        prompt=config.get("templatePath") or config.get("skill") or config.get("prompt"),
        artifact=config.get("outputFile") or config.get("filename") or config.get("artifact"),
        functions=[str(item) for item in (functions or [])],
        expected_files=[str(item) for item in (config.get("expectedFiles") or [])],
        retry_target=config.get("retryFromStepKey") or config.get("retryTarget"),
        ai_decision_allowed=str(config.get("type") or "ai") not in {"python", "validation", "gate", "manual"},
        deterministic_validation=str(config.get("type") or "") in {"python", "validation", "gate"} or bool(functions),
    )
