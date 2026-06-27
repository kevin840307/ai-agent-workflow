from __future__ import annotations

from fastapi import APIRouter

from app.domain import schemas
from app.services import project_service

router = APIRouter()


@router.post("/api/sessions")
async def create_session(body: schemas.CreateSessionRequest | None = None):
    return await project_service.create_project(body)


@router.get("/api/sessions")
async def list_sessions():
    return await project_service.list_projects()


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    return await project_service.delete_project(session_id)


@router.get("/api/sessions/{session_id}/messages")
async def list_messages(session_id: str):
    return await project_service.list_messages(session_id)


@router.post("/api/sessions/{session_id}/messages")
async def create_message(session_id: str, body: schemas.CreateMessageRequest):
    return await project_service.create_message(session_id, body)
