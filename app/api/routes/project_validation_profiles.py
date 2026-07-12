from __future__ import annotations

from fastapi import APIRouter

from app.domain.schemas import ProjectValidationProfileRequest
from app.workflow_runtime.project_validation_profile import (
    load_profile,
    refresh_profile,
    update_profile,
    verify_profile,
)

router = APIRouter()


@router.get("/api/project-validation-profile")
async def get_project_validation_profile(projectPath: str):
    return load_profile(projectPath, create=True)


@router.post("/api/project-validation-profile")
async def save_project_validation_profile(body: ProjectValidationProfileRequest):
    if body.refresh:
        return refresh_profile(body.project_path, preserve_custom_phases=False)
    return update_profile(body.project_path, body.profile or {})


@router.post("/api/project-validation-profile/verify")
async def verify_project_validation_profile(body: ProjectValidationProfileRequest):
    if body.profile:
        update_profile(body.project_path, body.profile)
    return await verify_profile(body.project_path, timeout_sec=body.timeout_sec or 900)
