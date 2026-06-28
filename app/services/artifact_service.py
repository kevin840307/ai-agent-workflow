from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.services import workflow_service


async def get_artifact(artifact_id: str) -> dict:
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
    return {"id": artifact_id, "name": path.name, "path": rel_path, "content": runtime.read_text(path)}
