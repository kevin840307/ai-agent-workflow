from __future__ import annotations

import json

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.runtime_modules import api as runtime
from app.domain import schemas
from app.services import workflow_service

router = APIRouter()


@router.post("/api/sessions/{session_id}/workflow-runs")
async def create_workflow_run(session_id: str, body: schemas.CreateRunRequest):
    return await workflow_service.create_workflow_run(session_id, body)


@router.get("/api/sessions/{session_id}/workflow-runs/latest")
async def get_latest_run_for_session(session_id: str):
    return await workflow_service.get_latest_run_for_session(session_id)


@router.get("/api/workflow-runs/active")
async def list_active_runs():
    return await workflow_service.list_active_runs()


@router.get("/api/workflow-runs/queue")
async def list_run_queue():
    return await workflow_service.list_run_queue()


@router.get("/api/workflow-runs/{run_id}")
async def get_run(run_id: str):
    return await workflow_service.get_run(run_id)


@router.post("/api/workflow-runs/{run_id}/retry")
async def retry_run(run_id: str, body: schemas.RetryRunRequest | None = None):
    return await workflow_service.retry_run(run_id, body)




@router.post("/api/workflow-runs/{run_id}/actions")
async def execute_run_action(run_id: str, body: schemas.RunActionRequest):
    return await workflow_service.execute_run_action(run_id, body)


@router.post("/api/workflow-runs/{run_id}/terminate")
async def terminate_run(run_id: str):
    return await workflow_service.terminate_run(run_id)


@router.post("/api/workflow-runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    return await workflow_service.cancel_run(run_id)


@router.post("/api/workflow-runs/{run_id}/answers")
async def submit_answers(run_id: str, body: schemas.SubmitAnswersRequest):
    return await workflow_service.submit_answers(run_id, body)


@router.post("/api/workflow-runs/{run_id}/guidance")
async def submit_guidance(run_id: str, body: schemas.SubmitGuidanceRequest):
    return await workflow_service.submit_guidance(run_id, body)


@router.post("/api/workflow-runs/{run_id}/steps/rerun")
async def rerun_step(run_id: str, body: schemas.RerunStepRequest | None = None):
    return await workflow_service.rerun_step(run_id, body)




@router.get("/api/workflow-runs/{run_id}/overview")
async def get_run_overview(run_id: str):
    return await workflow_service.get_run_overview(run_id)


@router.get("/api/workflow-runs/{run_id}/diagnostics")
async def get_run_diagnostics(run_id: str):
    return await workflow_service.get_run_diagnostics(run_id)


@router.post("/api/workflow-runs/{run_id}/artifacts/compact")
async def compact_run_artifacts(run_id: str):
    return await workflow_service.compact_run_artifacts_service(run_id)

@router.get("/api/workflow-runs/{run_id}/console")
async def get_run_console(run_id: str):
    return await workflow_service.get_run_console(run_id)


@router.get("/api/workflow-runs/{run_id}/diff")
async def get_run_diff(run_id: str):
    return await workflow_service.get_run_diff(run_id)


@router.get("/api/workflow-runs/{run_id}/patch")
async def get_patch_preview(run_id: str):
    return await workflow_service.get_patch_preview(run_id)


@router.post("/api/workflow-runs/{run_id}/patch/apply")
async def apply_patch(run_id: str, body: schemas.PatchApplyRequest | None = None):
    return await workflow_service.apply_run_patch(run_id, body)


@router.get("/api/workflow-runs/{run_id}/version-meta")
async def get_version_metadata(run_id: str):
    return await workflow_service.get_run_version_metadata(run_id)


@router.get("/api/workflow-runs/{run_id}/failures")
async def get_failure_classification(run_id: str):
    return await workflow_service.get_failure_classification(run_id)


@router.get("/api/workflow-runs/{run_id}/artifact-index")
async def get_run_artifact_index(run_id: str):
    return await workflow_service.get_run_artifact_index(run_id)


@router.get("/api/workflow-runs/{run_id}/consistency")
async def get_run_consistency(run_id: str):
    return await workflow_service.get_run_consistency(run_id)


@router.post("/api/workflow-runs/{run_id}/repair-artifacts")
async def repair_run_artifacts(run_id: str):
    return await workflow_service.repair_run_artifacts_service(run_id)


@router.get("/api/workflow-runs/{run_id}/debug-bundle")
async def get_run_debug_bundle(run_id: str):
    return await workflow_service.get_run_debug_bundle(run_id)

@router.get("/api/workflow-runs/{run_id}/lifecycle")
async def get_run_lifecycle(run_id: str):
    return await workflow_service.get_run_lifecycle(run_id)


@router.get("/api/workflow-runs/{run_id}/repair-policy")
async def get_run_repair_policy(run_id: str):
    return await workflow_service.get_run_repair_policy(run_id)


@router.post("/api/workflow-runs/{run_id}/steps/skip")
async def skip_step(run_id: str, body: schemas.StepControlRequest):
    return await workflow_service.skip_step(run_id, body)


@router.post("/api/workflow-runs/{run_id}/steps/pass")
async def mark_step_passed(run_id: str, body: schemas.StepControlRequest):
    return await workflow_service.mark_step_passed(run_id, body)


@router.post("/api/workflow-runs/{run_id}/resume")
async def resume_run(run_id: str, body: schemas.StepControlRequest | None = None):
    return await workflow_service.resume_run(run_id, body)


@router.get("/api/workflow-runs/{run_id}/export")
async def export_run(run_id: str):
    bundle = await workflow_service.export_run_bundle(run_id)
    return FileResponse(bundle, filename=bundle.name, media_type="application/zip")


@router.post("/api/workflow-runs/{run_id}/replay")
async def replay_run(run_id: str, body: schemas.CreateRunRequest | None = None):
    return await workflow_service.replay_run(run_id, body)


@router.post("/api/workflow-runs/{run_id}/simulate-question")
async def simulate_question(run_id: str):
    return await workflow_service.simulate_question(run_id)


@router.get("/api/workflow-runs/{run_id}/steps")
async def get_steps(run_id: str):
    return await workflow_service.get_steps(run_id)


@router.get("/api/workflow-runs/{run_id}/artifacts")
async def get_artifacts(run_id: str, view: str = Query(default="supporting", pattern="^(essential|supporting|all|diagnostic|debug)$")):
    return await workflow_service.get_artifacts(run_id, view=view)


@router.get("/api/workflow-runs/{run_id}/events")
async def events(run_id: str):
    await workflow_service.get_run(run_id)

    async def stream():
        async for queue in runtime.bus.subscribe(run_id):
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
