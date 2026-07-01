from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.services import workflow_asset_service
from app.workflow_runtime.step_utils import expected_files

VALID_STEP_TYPES = {"ai", "agent", "qwen", "review", "validation", "validator", "python", "test", "gate", "manual"}
VALID_FAIL_ACTIONS = {"same_step", "previous_step", "selected_step", "stop"}
VALID_REVIEW_MODES = {"", "none", "disabled", "current_session", "new_agent", "multi_agent"}
VALID_AGGREGATORS = {"", "keyword_confidence", "majority_vote", "all_must_pass"}
FUNCTIONS_REQUIRING_ARTIFACT = {"require_status_pass", "validate_security_candidates", "validate_security_report"}


def lint_workflow(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    steps = workflow.get("steps") or []
    if not isinstance(steps, list):
        return [_issue("steps", "Workflow steps must be a list.")]

    keys: list[str] = []
    for index, step in enumerate(steps):
        location = f"steps[{index}]"
        if not isinstance(step, dict):
            errors.append(_issue(location, "Step must be an object."))
            continue
        key = str(step.get("key") or "").strip()
        if not key:
            errors.append(_issue(f"{location}.key", "Step key is required."))
        elif not re.match(r"^[A-Za-z][A-Za-z0-9_\\-]*$", key):
            errors.append(_issue(f"{location}.key", "Step key must start with a letter and use letters, numbers, _ or -."))
        keys.append(key)

        step_type = str(step.get("type") or "ai")
        if step_type not in VALID_STEP_TYPES:
            errors.append(_issue(f"{location}.type", f"Unsupported step type: {step_type}"))

        fail_action = str(step.get("failAction") or "same_step")
        if fail_action not in VALID_FAIL_ACTIONS:
            errors.append(_issue(f"{location}.failAction", f"Unsupported fail action: {fail_action}"))

        template_path = str(step.get("templatePath") or "")
        if template_path:
            _check_bundle_path(template_path, f"{location}.templatePath", errors)

        for rel_path in expected_files({"config": step}):
            _check_expected_path(rel_path, f"{location}.expectedFiles", errors)

        function_id = _function_id(step.get("function") if step.get("function") is not None else step.get("validator"))
        if function_id and function_id != "consensus_agent":
            known_asset = workflow_asset_service.resolve_function_reference(function_id)
            if function_id not in PYTHON_FUNCTIONS and not known_asset:
                errors.append(_issue(f"{location}.function", f"Unknown Python function: {function_id}"))
        if function_id in FUNCTIONS_REQUIRING_ARTIFACT and not (step.get("outputFile") or step.get("filename")):
            errors.append(_issue(f"{location}.outputFile", f"{function_id} requires an output filename/artifact."))

        review_mode = str(step.get("reviewMode") or "")
        if review_mode not in VALID_REVIEW_MODES:
            errors.append(_issue(f"{location}.reviewMode", f"Unsupported review mode: {review_mode}"))

        aggregator = str(step.get("aggregatorFunction") or "")
        if aggregator not in VALID_AGGREGATORS:
            errors.append(_issue(f"{location}.aggregatorFunction", f"Unsupported aggregator: {aggregator}"))

        if bool(step.get("timeoutEnabled")):
            try:
                timeout_minutes = float(step.get("timeoutMinutes") or 0)
            except (TypeError, ValueError):
                timeout_minutes = 0
            if timeout_minutes <= 0:
                errors.append(_issue(f"{location}.timeoutMinutes", "Timeout must be greater than 0 when enabled."))

        try:
            max_retries = int(step.get("maxRetries", 0) or 0)
        except (TypeError, ValueError):
            max_retries = -1
        if max_retries < 0:
            errors.append(_issue(f"{location}.maxRetries", "Max retries cannot be negative."))

    duplicates = sorted({key for key in keys if key and keys.count(key) > 1})
    for key in duplicates:
        errors.append(_issue("steps.key", f"Duplicate step key: {key}"))

    available_keys = {key for key in keys if key}
    for index, step in enumerate(step for step in steps if isinstance(step, dict)):
        location = f"steps[{index}]"
        for field in ("retryFromStepKey", "failActionStepKey", "selectedStepKey"):
            target = str(step.get(field) or "").strip()
            if target and target not in available_keys:
                errors.append(_issue(f"{location}.{field}", f"Step target does not exist: {target}"))

    return errors


def assert_workflow_valid(workflow: dict[str, Any]) -> None:
    issues = lint_workflow(workflow)
    if issues:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WORKFLOW_CONFIG_INVALID",
                "message": "Workflow config is invalid.",
                "details": {"issues": issues},
            },
        )


def _function_id(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("function") or "")
    return str(value or "")


def _check_bundle_path(value: str, location: str, errors: list[dict[str, Any]]) -> None:
    path = Path(str(value).replace("\\", "/"))
    parts = [part for part in path.parts if part not in {"", "."}]
    if path.is_absolute() or any(part == ".." for part in parts):
        errors.append(_issue(location, "Path must stay inside the workflow bundle."))


def _check_expected_path(value: str, location: str, errors: list[dict[str, Any]]) -> None:
    normalized = str(value or "").replace("\\", "/").strip()
    path = Path(normalized)
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if path.is_absolute() or not normalized or any(part == ".." for part in parts) or ".qwen-workflow" in parts:
        errors.append(_issue(location, f"Unsafe expected file path: {value}"))


def _issue(location: str, message: str) -> dict[str, Any]:
    return {"field": location, "message": message}
