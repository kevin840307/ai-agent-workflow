from __future__ import annotations

from fastapi import APIRouter

from app.services import workflow_case_service

router = APIRouter()


@router.get("/api/workflow-cases")
async def list_workflow_cases():
    return {"cases": workflow_case_service.list_cases()}


@router.get("/api/workflow-cases/{case_id}")
async def get_workflow_case(case_id: str):
    return workflow_case_service.get_case(case_id)
