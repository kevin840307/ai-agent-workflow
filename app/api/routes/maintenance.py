from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import maintenance_service

router = APIRouter()


@router.post("/api/maintenance/cleanup")
async def cleanup(keep_per_project: int = Query(default=20, ge=1, le=500)):
    return await maintenance_service.cleanup_runs(keep_per_project=keep_per_project)
