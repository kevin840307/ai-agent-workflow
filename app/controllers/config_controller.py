from __future__ import annotations

from fastapi import APIRouter

from app.domain import schemas
from app.services import config_service

router = APIRouter()


@router.get("/api/config")
async def get_config():
    return config_service.get_config()


@router.post("/api/config/qwen")
async def update_agent_config(body: schemas.AgentSettingsRequest):
    return config_service.update_agent_config(body)


@router.post("/api/config/agents")
async def update_agents_config(body: schemas.AgentSettingsRequest):
    return config_service.update_agent_config(body)
