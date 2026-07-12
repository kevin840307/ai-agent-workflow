from __future__ import annotations

from typing import Any

from app.persistence.repositories import store as store_repository
from app.services import workflow_config_service
from app.services.workflow_lint_service import lint_workflow
from app.services.workflow_asset_validator import validate_all_workflows
from app.workflow_runtime.benchmark import summarize_runs
from app.workflow_runtime.run_console import build_run_console
from app.workflow_runtime.versioning import build_version_metadata
from app.services.real_agent_matrix_service import build_real_agent_matrix
from app.workflow_runtime.repair_policy import policy_for_failure


async def workflow_benchmarks() -> dict[str, Any]:
    data = await store_repository.read()
    return summarize_runs(data.get("runs", []))


async def validate_workflows(project_path: str | None = None) -> dict[str, Any]:
    return await validate_all_workflows(project_path)


async def real_agent_matrix(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    return build_real_agent_matrix(agents=body.get("agents"), workflows=body.get("workflows"), cases=body.get("cases"), mode=body.get("mode"), output_root=body.get("output_root"))


def regression_workflow_template() -> dict[str, Any]:
    return {
        "schema": "aiwf.regression-workflow-template.v1",
        "template_id": "regression-test-case-generation",
        "workflow_id": "general-auto-development",
        "purpose": "Generate SOP SQL, runtime SQL, expected result, validation.py, markdown case, and dry-run report.",
        "recommended_inputs": [
            "SOP name / Block name / CaseId",
            "Acceptance criteria",
            "Runtime type combinations such as typeA/typeB",
            "Expected DB/log/web/monitoring evidence",
        ],
        "outputs": [
            "regression-context.md",
            "sop-definition.sql",
            "runtime-test-data.sql",
            "expected-result.md",
            "validation.py",
            "regression-test-case.md",
            "dry-run-report.md",
        ],
    }


def small_model_repair_policy(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    return policy_for_failure(body.get("message") or body.get("error"), step_key=body.get("step_key"), error_code=body.get("error_code"), retry_count=int(body.get("retry_count") or 0))


__all__ = ["workflow_benchmarks", "validate_workflows", "real_agent_matrix", "build_run_console", "build_version_metadata", "regression_workflow_template", "small_model_repair_policy"]
