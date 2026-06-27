from __future__ import annotations

from fastapi import APIRouter

from app.services import artifact_service

router = APIRouter()


@router.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    return await artifact_service.get_artifact(artifact_id)
