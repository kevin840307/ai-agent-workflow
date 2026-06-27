from __future__ import annotations

from fastapi import APIRouter

from app.domain import schemas
from app.services import config_service

router = APIRouter()


@router.get("/api/config")
async def get_config():
    return config_service.get_config()


@router.post("/api/config/qwen")
async def update_qwen_config(body: schemas.QwenSettingsRequest):
    return config_service.update_qwen_config(body)
