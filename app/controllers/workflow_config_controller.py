from __future__ import annotations

from fastapi import APIRouter, Body

from app.services import workflow_config_service

router = APIRouter()


@router.get("/api/workflows")
async def list_workflows():
    return await workflow_config_service.list_workflows()


@router.get("/api/workflows/functions")
async def get_workflow_functions():
    return await workflow_config_service.get_functions()


@router.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    return await workflow_config_service.get_workflow(workflow_id)


@router.post("/api/workflows")
async def create_workflow(workflow: dict = Body(...)):
    return await workflow_config_service.upsert_workflow(workflow)


@router.put("/api/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, workflow: dict = Body(...)):
    workflow["id"] = workflow_id
    return await workflow_config_service.upsert_workflow(workflow)


@router.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    return await workflow_config_service.delete_workflow(workflow_id)
