from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel

from app.services import workflow_asset_service


router = APIRouter()


class WorkflowAssetWriteRequest(BaseModel):
    path: str
    content: str
    project_path: str | None = None
    scope: str = "global"
    overwrite: bool = True


class WorkflowContractWriteRequest(BaseModel):
    contract: dict[str, Any]
    project_path: str | None = None
    scope: str = "global"


@router.get("/api/workflow-assets")
async def list_workflow_assets(project_path: str | None = Query(default=None)):
    return workflow_asset_service.list_assets(project_path)


@router.get("/api/workflow-assets/file")
async def read_workflow_asset(path: str = Query(...), project_path: str | None = Query(default=None)):
    return workflow_asset_service.read_asset(path, project_path)


@router.put("/api/workflow-assets/file")
async def write_workflow_asset(body: WorkflowAssetWriteRequest):
    return workflow_asset_service.write_asset(
        body.path,
        body.content,
        body.project_path,
        scope=body.scope,
        overwrite=body.overwrite,
    )


@router.post("/api/workflow-assets/contract")
async def write_workflow_contract(body: WorkflowContractWriteRequest = Body(...)):
    return workflow_asset_service.write_contract(body.contract, body.project_path, scope=body.scope)


@router.post("/api/workflow-assets/apply-contract")
async def preview_contract_application(body: dict[str, Any] = Body(...)):
    workflow = body.get("workflow") or {}
    project_path = body.get("project_path")
    return workflow_asset_service.apply_contracts_to_workflow(workflow, project_path)
