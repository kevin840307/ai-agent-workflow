from __future__ import annotations

from fastapi import APIRouter, Body

from app.services import context_pack_service

router = APIRouter()


@router.get("/api/context-packs")
async def list_context_packs():
    return context_pack_service.list_context_packs()


@router.get("/api/context-packs/{pack_id}")
async def get_context_pack(pack_id: str):
    return context_pack_service.get_context_pack(pack_id)


@router.put("/api/context-packs/{pack_id}")
async def upsert_context_pack(pack_id: str, body: dict = Body(...)):
    body = dict(body or {})
    body["id"] = pack_id
    return context_pack_service.save_context_pack(body)
