from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.analytics_service import analytics_summary

router = APIRouter()


@router.get("/api/analytics/summary")
async def get_analytics_summary(limit: int = Query(default=500, ge=1, le=5000)):
    return await analytics_summary(limit=limit)
