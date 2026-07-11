from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.persistence.repositories import store as store_repository
from app.runtime_modules import api as runtime
from app.workflow_runtime.benchmark_catalog import benchmark_catalog, benchmark_summary
from app.workflow_runtime.model_capabilities import MODEL_CAPABILITY_PROFILES, resolve_model_capability
from app.workflow_runtime.release_manager import upgrade_readiness, version_manifest, write_version_manifest
from app.workflow_runtime.validators import detect_validator_plans, execute_validator_plan


class ValidatorRunRequest(BaseModel):
    project_path: str
    validator_id: str | None = None
    timeout_sec: int = Field(default=900, ge=1, le=7200)

router = APIRouter()


@router.get("/api/productization/version")
async def product_version():
    path = write_version_manifest()
    return {"version": version_manifest(), "manifest_path": str(path)}


@router.get("/api/productization/upgrade-readiness")
async def product_upgrade_readiness():
    return upgrade_readiness(runtime.store_path())


@router.get("/api/productization/model-profiles")
async def model_profiles():
    return {"profiles": MODEL_CAPABILITY_PROFILES}


@router.get("/api/productization/model-profiles/{profile_id}")
async def model_profile(profile_id: str):
    return resolve_model_capability(profile_id)


@router.get("/api/productization/validators")
async def validator_plans(project_path: str):
    project = runtime.resolve_project_path(project_path)
    return {"project_path": str(project), "validators": detect_validator_plans(project)}


@router.post("/api/productization/validators/run")
async def run_validator(request: ValidatorRunRequest):
    project = runtime.resolve_project_path(request.project_path)
    return await execute_validator_plan(project, validator_id=request.validator_id, timeout_sec=request.timeout_sec)


@router.get("/api/benchmarks/catalog")
async def benchmarks_catalog():
    return benchmark_catalog()


@router.get("/api/benchmarks/summary")
async def benchmarks_summary():
    data = await store_repository.read()
    return benchmark_summary(list(data.get("runs") or []))
