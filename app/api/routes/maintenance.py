from __future__ import annotations

from pathlib import Path

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


@router.post("/api/maintenance/store/compact")
async def compact_store():
    from app.runtime_modules import api as runtime

    store = runtime.store
    if not hasattr(store, "compact_sync"):
        return {"schema": "aiwf.store-compaction.v1", "supported": False, "backend": runtime.store_backend_name()}
    result = store.compact_sync()
    return {"schema": "aiwf.store-compaction.v1", "supported": True, "backend": runtime.store_backend_name(), **result}


@router.get("/api/maintenance/store/status")
async def store_status():
    from app.runtime_modules import api as runtime

    store = runtime.store
    counts = store.projection_counts() if hasattr(store, "projection_counts") else {}
    path = runtime.store_path()
    wal_path = Path(f"{path}-wal")
    return {
        "schema": "aiwf.store-status.v2",
        "backend": runtime.store_backend_name(),
        "path": str(path),
        "projection_counts": counts,
        "wal_enabled": runtime.store_backend_name() == "sqlite",
        "database_bytes": path.stat().st_size if path.exists() else 0,
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
    }


@router.get("/api/maintenance/invariants")
async def runtime_invariants(repair: bool = Query(default=False)):
    return await maintenance_service.inspect_runtime_invariants(repair=repair)
