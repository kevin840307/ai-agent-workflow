from __future__ import annotations

from fastapi import APIRouter

from app.domain.schemas import OptimizationRequest
from app.services.optimization_service import recommend_execution

router = APIRouter()


@router.post("/api/optimization/recommend")
async def recommend(body: OptimizationRequest):
    return await recommend_execution(
        body.requirement,
        project_path=body.project_path,
        workflow_id=body.workflow_id,
        agent=body.agent,
    )
