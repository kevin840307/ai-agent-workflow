from __future__ import annotations

from fastapi import APIRouter, Body, Query

from app.services import workflow_productization_service

router = APIRouter()


@router.get("/api/workflow-benchmarks")
async def workflow_benchmarks():
    return await workflow_productization_service.workflow_benchmarks()


@router.get("/api/workflows/validate")
async def validate_workflows(project_path: str | None = Query(default=None)):
    return await workflow_productization_service.validate_workflows(project_path)


@router.post("/api/real-agent-matrix")
async def real_agent_matrix(body: dict | None = Body(default=None)):
    return await workflow_productization_service.real_agent_matrix(body)


@router.get("/api/regression-workflow/template")
async def regression_workflow_template():
    return workflow_productization_service.regression_workflow_template()


@router.post("/api/small-model-repair-policy")
async def small_model_repair_policy(body: dict | None = Body(default=None)):
    return workflow_productization_service.small_model_repair_policy(body)
