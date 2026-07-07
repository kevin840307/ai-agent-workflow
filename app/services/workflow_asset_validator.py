from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services import workflow_asset_service, workflow_config_service
from app.services.workflow_lint_service import lint_workflow
from app.workflow_runtime.step_utils import parse_function_refs
from app.workflow_engine.contracts import normalize_step_contract
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS

VALID_FINAL_KEYS = {"final_gate", "final_review", "finalize_security_report", "dry_run"}
VALID_STEP_TYPES = {"ai", "review", "python", "validation", "check", "gate", "manual", "command", "agent", "qwen"}


def _issue(severity: str, field: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "field": field, "message": message}


def _exists_asset(path: str, project_path: str | None = None) -> bool:
    try:
        workflow_asset_service.resolve_asset_path(path, project_path)
        return True
    except Exception:
        return False


def validate_workflow(workflow: dict[str, Any], *, project_path: str | None = None) -> dict[str, Any]:
    errors = [_issue("error", item.get("field", "workflow"), item.get("message", str(item))) for item in lint_workflow(workflow)]
    warnings: list[dict[str, Any]] = []
    steps = [step for step in workflow.get("steps", []) if isinstance(step, dict)]
    step_keys = [str(step.get("key") or "") for step in steps]
    if not steps:
        errors.append(_issue("error", "steps", "Workflow must contain at least one step."))
    if steps and not any(key in VALID_FINAL_KEYS or key.endswith("_gate") for key in step_keys[-2:]):
        warnings.append(_issue("warning", "steps.final", "Workflow does not end with an obvious final gate/review step."))
    normalized_contracts: list[dict[str, Any]] = []
    key_set = set(step_keys)
    for index, step in enumerate(steps):
        location = f"steps[{index}]"
        contract = normalize_step_contract(step)
        normalized_contracts.append({
            "key": contract.key,
            "type": contract.type,
            "prompt": contract.prompt,
            "artifact": contract.artifact,
            "functions": contract.functions,
            "expected_files": contract.expected_files,
            "retry_target": contract.retry_target,
            "ai_decision_allowed": contract.ai_decision_allowed,
            "deterministic_validation": contract.deterministic_validation,
        })
        if not contract.key:
            errors.append(_issue("error", f"{location}.key", "Step key is required."))
        if contract.type not in VALID_STEP_TYPES:
            warnings.append(_issue("warning", f"{location}.type", f"Unknown step type '{contract.type}', runtime may treat it as an agent step."))
        template_path = str(step.get("templatePath") or step.get("skillPath") or step.get("skill") or "").strip()
        if contract.type in {"ai", "review", "agent", "qwen", "command"} and not template_path and not contract.functions:
            warnings.append(_issue("warning", f"{location}.templatePath", "Agent/review step has no prompt template or runtime function."))
        if template_path and template_path.startswith("steps/") and not _exists_asset(template_path, project_path):
            warnings.append(_issue("warning", f"{location}.templatePath", f"Prompt template not found: {template_path}"))
        contract_path = str(step.get("contractPath") or step.get("metadataPath") or step.get("contract") or "").strip()
        if not contract_path:
            warnings.append(_issue("warning", f"{location}.contractPath", "Step has no explicit contractPath; normalized in-memory config is still used."))
        if contract_path and contract_path.startswith("contracts/") and not _exists_asset(contract_path, project_path):
            errors.append(_issue("error", f"{location}.contractPath", f"Contract not found: {contract_path}"))
        retry_target = str(step.get("retryFromStepKey") or step.get("retryTarget") or "").strip()
        if retry_target and retry_target not in key_set:
            errors.append(_issue("error", f"{location}.retryFromStepKey", f"Retry target does not exist: {retry_target}"))
        try:
            max_retries = int(step.get("maxRetries", step.get("retry", 0)) or 0)
        except (TypeError, ValueError):
            errors.append(_issue("error", f"{location}.maxRetries", "Retry budget must be numeric."))
            max_retries = 0
        if max_retries > 20:
            warnings.append(_issue("warning", f"{location}.maxRetries", f"High retry budget may hide infinite retry risk: {max_retries}"))
        functions = parse_function_refs(step.get("functions") if step.get("functions") is not None else step.get("function"))
        if contract.type in {"python", "validation", "check", "gate"} and not functions:
            warnings.append(_issue("warning", f"{location}.functions", f"Deterministic step type '{contract.type}' has no runtime function."))
        for function_id in functions:
            if function_id not in PYTHON_FUNCTIONS and not workflow_asset_service.resolve_function_reference(function_id):
                errors.append(_issue("error", f"{location}.functions", f"Unknown runtime function: {function_id}"))
    return {
        "id": workflow.get("id"),
        "name": workflow.get("name"),
        "version": workflow.get("version") or workflow.get("updated_at") or "v1",
        "schema": "aiwf.workflow-contract.v1",
        "step_contracts": normalized_contracts,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issue_count": len(errors) + len(warnings),
        "issues": [*errors, *warnings],
    }


async def validate_all_workflows(project_path: str | None = None) -> dict[str, Any]:
    payload = await workflow_config_service.list_workflows(project_path)
    raw_workflows = [payload.get("system"), *(payload.get("systems") or []), *(payload.get("custom") or [])]
    workflows = [validate_workflow(workflow, project_path=project_path) for workflow in raw_workflows if workflow]
    return {
        "schema": "aiwf.workflow-validator.v3",
        "ok": all(item["error_count"] == 0 for item in workflows),
        "workflow_count": len(workflows),
        "error_count": sum(item["error_count"] for item in workflows),
        "warning_count": sum(item["warning_count"] for item in workflows),
        "workflows": workflows,
    }
