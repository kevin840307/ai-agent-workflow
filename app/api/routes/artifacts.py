from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.services import artifact_service

router = APIRouter()


@router.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    return await artifact_service.get_artifact(artifact_id)


@router.get("/api/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    path, media_type, filename = await artifact_service.get_artifact_download(artifact_id)
    return FileResponse(path, media_type=media_type, filename=filename)
