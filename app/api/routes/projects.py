from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import json

from app.domain import schemas
from app.persistence.repositories import store as store_repository
from app.api.dependencies import get_runtime_context
from app.core.runtime_context import RuntimeContext
from app.services import project_service

router = APIRouter()


@router.post("/api/sessions")
async def create_session(body: schemas.CreateSessionRequest | None = None, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.create_project(body, context=context)


@router.get("/api/sessions")
async def list_sessions(context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.list_projects(context=context)


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.delete_project(session_id, context=context)


@router.post("/api/sessions/{session_id}/reset")
async def reset_session(session_id: str, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.reset_project(session_id, context=context)


@router.get("/api/sessions/{session_id}/messages")
async def list_messages(session_id: str, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.list_messages(session_id, context=context)


@router.post("/api/sessions/{session_id}/messages")
async def create_message(session_id: str, body: schemas.CreateMessageRequest, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.create_message(session_id, body, context=context)


@router.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, body: schemas.CreateMessageRequest, context: RuntimeContext = Depends(get_runtime_context)):
    return await project_service.chat(session_id, body, context=context)


@router.get("/api/sessions/{session_id}/chat-events")
async def chat_events(session_id: str, context: RuntimeContext = Depends(get_runtime_context)):
    data = await store_repository.read(context)
    if not any(session.get("id") == session_id for session in data.get("sessions", [])):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    stream_id = f"chat-{session_id}"

    async def stream():
        async for queue in context.bus.subscribe(stream_id):
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
