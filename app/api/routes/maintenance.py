from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import maintenance_service

router = APIRouter()


@router.post("/api/maintenance/cleanup")
async def cleanup(
    keep_per_project: int = Query(default=20, ge=1, le=500),
    older_than_days: int | None = Query(default=None, ge=1, le=3650),
    dry_run: bool = Query(default=False),
    include_orphan_workspaces: bool = Query(default=False),
):
    return await maintenance_service.cleanup_runs(
        keep_per_project=keep_per_project,
        older_than_days=older_than_days,
        dry_run=dry_run,
        include_orphan_workspaces=include_orphan_workspaces,
    )
