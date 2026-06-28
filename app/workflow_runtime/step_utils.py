from __future__ import annotations

from typing import Any


def format_exception(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return f"{type(exc).__name__}: {exc!r}"


def step_prompt_name(step_record: dict[str, Any], default: str) -> str:
    config = step_record.get("config") or {}
    return config.get("templatePath") or default


def step_artifact_name(step_record: dict[str, Any], default: str) -> str:
    config = step_record.get("config") or {}
    return config.get("outputFile") or config.get("filename") or default


def step_validator_name(step_record: dict[str, Any]) -> str:
    config = step_record.get("config") or {}
    validator = config.get("validator")
    if isinstance(validator, dict):
        return validator.get("id") or ""
    return validator or ""


def step_agent_name(step_record: dict[str, Any], default: str = "") -> str:
    config = step_record.get("config") or {}
    return step_record.get("agent") or config.get("agent") or config.get("provider") or default
