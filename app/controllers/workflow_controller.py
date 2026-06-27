from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import runtime
from app.domain import schemas
from app.services import workflow_service

router = APIRouter()


@router.post("/api/sessions/{session_id}/workflow-runs")
async def create_workflow_run(session_id: str, body: schemas.CreateRunRequest):
    return await workflow_service.create_workflow_run(session_id, body)


@router.get("/api/sessions/{session_id}/workflow-runs/latest")
async def get_latest_run_for_session(session_id: str):
    return await workflow_service.get_latest_run_for_session(session_id)


@router.get("/api/workflow-runs/{run_id}")
async def get_run(run_id: str):
    return await workflow_service.get_run(run_id)


@router.post("/api/workflow-runs/{run_id}/retry")
async def retry_run(run_id: str, body: schemas.RetryRunRequest | None = None):
    return await workflow_service.retry_run(run_id, body)


@router.post("/api/workflow-runs/{run_id}/terminate")
async def terminate_run(run_id: str):
    return await workflow_service.terminate_run(run_id)


@router.post("/api/workflow-runs/{run_id}/answers")
async def submit_answers(run_id: str, body: schemas.SubmitAnswersRequest):
    return await workflow_service.submit_answers(run_id, body)


@router.post("/api/workflow-runs/{run_id}/guidance")
async def submit_guidance(run_id: str, body: schemas.SubmitGuidanceRequest):
    return await workflow_service.submit_guidance(run_id, body)


@router.post("/api/workflow-runs/{run_id}/simulate-question")
async def simulate_question(run_id: str):
    return await workflow_service.simulate_question(run_id)


@router.get("/api/workflow-runs/{run_id}/steps")
async def get_steps(run_id: str):
    return await workflow_service.get_steps(run_id)


@router.get("/api/workflow-runs/{run_id}/artifacts")
async def get_artifacts(run_id: str):
    return await workflow_service.get_artifacts(run_id)


@router.get("/api/workflow-runs/{run_id}/events")
async def events(run_id: str):
    await workflow_service.get_run(run_id)

    async def stream():
        async for queue in runtime.bus.subscribe(run_id):
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
