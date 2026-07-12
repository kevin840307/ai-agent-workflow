from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.services import workflow_service
from app.workflow_runtime.artifact_policy import enrich_artifact_records, artifact_preview_kind


async def resolve_artifact(artifact_id: str) -> tuple[dict[str, Any], Path, str, dict[str, Any]]:
    run_id, _, encoded_path = artifact_id.partition(":")
    if not run_id or not encoded_path:
        raise HTTPException(status_code=404, detail="Artifact not found")
    rel_path = encoded_path.replace("|", "/")
    run = await workflow_service.get_run(run_id)
    workspace = Path(run["workspace"]).resolve()
    path = (workspace / rel_path).resolve()
    if path != workspace and workspace not in path.parents:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    metadata = next((item for item in run.get("artifacts") or [] if item.get("id") == artifact_id or item.get("path") == rel_path), {})
    enriched = enrich_artifact_records([metadata])[0] if metadata else {}
    return run, path, rel_path, enriched


async def get_artifact(artifact_id: str) -> dict:
    _run, path, rel_path, enriched = await resolve_artifact(artifact_id)
    media_type = str(enriched.get("media_type") or mimetypes.guess_type(path.name)[0] or "text/plain")
    role = str(enriched.get("role") or "unclassified")
    preview_kind = str(enriched.get("preview_kind") or artifact_preview_kind(media_type=media_type, role=role))
    content = "" if preview_kind == "binary" else runtime.read_text(path)
    return {
        **enriched,
        "id": artifact_id,
        "name": path.name,
        "path": rel_path,
        "media_type": media_type,
        "preview_kind": preview_kind,
        "preview_available": preview_kind != "binary",
        "content": content,
    }


async def get_artifact_download(artifact_id: str) -> tuple[Path, str, str]:
    _run, path, _rel_path, enriched = await resolve_artifact(artifact_id)
    media_type = str(enriched.get("media_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return path, media_type, path.name
