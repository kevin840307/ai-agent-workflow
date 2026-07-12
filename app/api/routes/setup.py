from __future__ import annotations

from fastapi import APIRouter, Query

from app.domain.schemas import SetupSmokeRequest

from app.services import setup_service, provider_connectivity_service

router = APIRouter()


@router.get("/api/setup/status")
async def setup_status(project_path: str | None = Query(default=None, alias="projectPath")):
    return await setup_service.setup_status(project_path)


@router.post("/api/setup/smoke")
async def setup_smoke(body: SetupSmokeRequest):
    return await setup_service.setup_smoke_test(
        body.project_path,
        agent_name=body.agent,
        run_agent=body.run_agent,
    )


@router.get("/api/setup/connectivity")
async def setup_connectivity(projectPath: str | None = None, agent: str | None = None):
    return await provider_connectivity_service.connectivity_status(projectPath, agent)
