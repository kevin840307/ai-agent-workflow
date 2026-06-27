from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

from app import runtime
from app.repositories import store_repository


async def create_project(body: runtime.CreateSessionRequest | None = None) -> dict:
    body = body or runtime.CreateSessionRequest()
    session_id = str(uuid.uuid4())
    project_path = str(runtime.resolve_project_path(body.project_path or str(runtime.ROOT)))
    title = (body.title or "").strip() or Path(project_path).name or "New Project"
    session = {
        "id": session_id,
        "qwen_session_id": session_id,
        "title": title,
        "project_path": project_path,
        "created_at": runtime.utc_now(),
        "updated_at": runtime.utc_now(),
    }
    return await store_repository.mutate(lambda data: (data["sessions"].insert(0, session), session)[1])


async def list_projects() -> list[dict]:
    return (await store_repository.read())["sessions"]


async def delete_project(session_id: str) -> dict:
    session_workspace = (runtime.WORKSPACES_DIR / f"session-{session_id}").resolve()
    workspace_root = runtime.WORKSPACES_DIR.resolve()
    data = await store_repository.read()
    run_workspaces = [
        Path(run["workspace"]).resolve()
        for run in data.get("runs", [])
        if run.get("session_id") == session_id and run.get("workspace")
    ]

    def remove(data):
        if not any(session["id"] == session_id for session in data["sessions"]):
            raise HTTPException(status_code=404, detail="Session not found")
        data["sessions"] = [session for session in data["sessions"] if session["id"] != session_id]
        data["messages"] = [message for message in data["messages"] if message["session_id"] != session_id]
        data["runs"] = [run for run in data["runs"] if run["session_id"] != session_id]
        return {"ok": True}

    result = await store_repository.mutate(remove)
    if session_workspace.exists():
        if workspace_root not in session_workspace.parents:
            raise HTTPException(status_code=400, detail="Invalid workspace path")
        shutil.rmtree(session_workspace)
    for run_workspace in run_workspaces:
        if not run_workspace.exists() or run_workspace == session_workspace:
            continue
        parts = set(run_workspace.parts)
        if ".qwen-workflow" not in parts or "runs" not in parts:
            continue
        shutil.rmtree(run_workspace)
    return result


async def list_messages(session_id: str) -> list[dict]:
    data = await store_repository.read()
    return [msg for msg in data["messages"] if msg["session_id"] == session_id]


async def create_message(session_id: str, body: runtime.CreateMessageRequest) -> dict:
    msg = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": "user",
        "content": body.content,
        "created_at": runtime.utc_now(),
    }

    def add(data):
        if not any(session["id"] == session_id for session in data["sessions"]):
            raise HTTPException(status_code=404, detail="Session not found")
        data["messages"].append(msg)
        for session in data["sessions"]:
            if session["id"] == session_id:
                session["title"] = body.content.strip()[:60] or session["title"]
                session["updated_at"] = runtime.utc_now()
        return msg

    return await store_repository.mutate(add)
