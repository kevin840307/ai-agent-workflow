from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.runtime_modules import api as runtime
from app.api.errors import http_exception_handler, validation_exception_handler
from app.api.routes import artifacts, config, maintenance, projects, workflow_assets, workflow_runs, workflows, workflow_cases, validation_scripts, context_packs, workflow_productization
from app.core.metrics import metrics
from app.services import workflow_asset_service, workflow_config_service, health_service


app = FastAPI(title="Agent Workflow Web MVP")
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


@app.on_event("startup")
async def startup() -> None:
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    if workers and workers != "1":
        raise RuntimeError("This single-machine MVP requires workers=1. Run uvicorn with --workers 1.")
    runtime.ensure_dirs()
    runtime.store.load_sync()
    runtime.mark_interrupted_runs()
    workflow_asset_service.ensure_asset_dirs()
    workflow_config_service.ensure_system_workflow()
    workflow_config_service.ensure_sample_workflow()
    context_pack_service = __import__("app.services.context_pack_service", fromlist=["ensure_context_pack_dirs"])
    context_pack_service.ensure_context_pack_dirs()


@app.get("/")
async def index():
    return FileResponse(runtime.STATIC_DIR / "index.html")

@app.get("/workflow-designer")
@app.get("/workflow-designer.html")
async def workflow_designer():
    return FileResponse(runtime.STATIC_DIR / "workflow-designer.html")


@app.get("/ai-workflow-assets")
@app.get("/ai-workflow-assets.html")
async def ai_workflow_assets():
    return FileResponse(runtime.STATIC_DIR / "ai-workflow-assets.html")


@app.get("/health")
@app.get("/api/health")
async def health():
    return await health_service.health_summary(deep=False)


@app.get("/api/health/deep")
async def deep_health():
    return await health_service.health_summary(deep=True)


@app.get("/ready")
async def ready():
    checks = {
        "storeReadable": runtime.STORE_FILE.exists(),
        "storeWritable": os.access(runtime.STORE_FILE.parent, os.W_OK),
        "dataWritable": os.access(runtime.DATA_DIR, os.W_OK),
        "staticAvailable": (runtime.STATIC_DIR / "index.html").exists(),
        "designerAvailable": (runtime.STATIC_DIR / "workflow-designer.html").exists(),
        "assetsPageAvailable": (runtime.STATIC_DIR / "ai-workflow-assets.html").exists(),
        "aiWorkflowWritable": os.access(workflow_asset_service.GLOBAL_ASSET_ROOT, os.W_OK),
    }
    ok = all(checks.values())
    return {"ok": ok, "status": "ready" if ok else "not_ready", "checks": checks}


@app.get("/metrics")
async def get_metrics():
    data = await runtime.store.read()
    active_runs = sum(1 for run in data.get("runs", []) if run.get("status") in {"queued", "running", "waiting_input", "cancelling"})
    return metrics.snapshot(active_runs=active_runs)

app.mount("/static", StaticFiles(directory=runtime.STATIC_DIR), name="static")

app.include_router(config.router)
app.include_router(projects.router)
app.include_router(workflow_productization.router)
app.include_router(workflows.router)
app.include_router(workflow_cases.router)
app.include_router(validation_scripts.router)
app.include_router(context_packs.router)
app.include_router(workflow_assets.router)
app.include_router(workflow_runs.router)
app.include_router(artifacts.router)
app.include_router(maintenance.router)
