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


@router.post("/api/maintenance/store/backup")
async def backup_store():
    from app.runtime_modules import api as runtime

    store = runtime.store
    if not hasattr(store, "backup_sync"):
        return {"schema": "aiwf.store-backup.v1", "supported": False, "backend": runtime.store_backend_name()}
    path = store.backup_sync()
    return {"schema": "aiwf.store-backup.v1", "supported": True, "backend": runtime.store_backend_name(), "path": str(path), "size_bytes": path.stat().st_size}


@router.get("/api/maintenance/store/status")
async def store_status():
    from app.runtime_modules import api as runtime

    store = runtime.store
    counts = store.projection_counts() if hasattr(store, "projection_counts") else {}
    return {
        "schema": "aiwf.store-status.v1",
        "backend": runtime.store_backend_name(),
        "path": str(runtime.store_path()),
        "projection_counts": counts,
        "wal_enabled": runtime.store_backend_name() == "sqlite",
    }
