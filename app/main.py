from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.runtime_modules import api as runtime
from app.api.errors import http_exception_handler, validation_exception_handler
from app.api.routes import artifacts, config, maintenance, projects, workflow_assets, workflow_runs, workflows, workflow_cases, validation_scripts, context_packs, workflow_productization, setup, analytics, optimization, productization_v9, project_validation_profiles
from app.core.metrics import metrics
from app.services import workflow_asset_service, workflow_config_service, health_service, workflow_service, maintenance_service
from app.agents.process_supervisor import terminate_async_process_tree
from app.workflow_runtime.qwen_serve import shutdown_qwen_serve

_invariant_stop: asyncio.Event | None = None
_invariant_task: asyncio.Task | None = None


async def startup() -> None:
    global _invariant_stop, _invariant_task
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    if workers and workers != "1":
        raise RuntimeError("This single-machine MVP requires workers=1. Run uvicorn with --workers 1.")
    runtime.ensure_dirs()
    # Clean up controller-managed child processes that survived an abrupt
    # controller exit before restoring persisted runs.
    reaper = getattr(runtime.running_processes, "reap_orphans", None)
    if callable(reaper):
        await asyncio.to_thread(reaper)
    runtime.store.load_sync()
    runtime.mark_interrupted_runs()
    workflow_asset_service.ensure_asset_dirs()
    workflow_config_service.ensure_system_workflow()
    context_pack_service = __import__("app.services.context_pack_service", fromlist=["ensure_context_pack_dirs"])
    context_pack_service.ensure_context_pack_dirs()
    await workflow_service.auto_resume_unattended_runs()
    if os.environ.get("AIWF_INVARIANT_MONITOR", "1").lower() not in {"0", "false", "no", "off"}:
        _invariant_stop = asyncio.Event()
        _invariant_task = asyncio.create_task(
            maintenance_service.runtime_invariant_monitor(
                _invariant_stop,
                interval_seconds=int(os.environ.get("AIWF_INVARIANT_INTERVAL_SEC", "60") or 60),
            ),
            name="aiwf-invariant-monitor",
        )


async def shutdown() -> None:
    """Gracefully stop controller-owned work before the event loop closes."""
    global _invariant_stop, _invariant_task
    if _invariant_stop is not None:
        _invariant_stop.set()
    if _invariant_task is not None:
        _invariant_task.cancel()
        with suppress(asyncio.CancelledError):
            await _invariant_task
    _invariant_stop = None
    _invariant_task = None
    tasks = [task for task in runtime.running_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=8)
    runtime.running_tasks.clear()

    processes = list(runtime.running_processes.values())
    for process in processes:
        if process.returncode is None:
            with suppress(Exception):
                await terminate_async_process_tree(process, grace_sec=1.5)
    runtime.running_processes.clear()

    # Persist active runs as recoverable and release their project locks before
    # the process exits. This also keeps TestClient teardown deterministic.
    with suppress(Exception):
        runtime.mark_interrupted_runs()
    with suppress(Exception):
        await asyncio.to_thread(shutdown_qwen_serve)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(title="Agent Workflow Web MVP", lifespan=lifespan)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


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
    store_path = runtime.store_path()
    checks = {
        "storeBackend": runtime.store_backend_name(),
        "storePath": str(store_path),
        "storeReadable": store_path.exists(),
        "storeWritable": os.access(store_path.parent, os.W_OK),
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
app.include_router(setup.router)
app.include_router(analytics.router)
app.include_router(optimization.router)
app.include_router(productization_v9.router)
app.include_router(projects.router)
app.include_router(project_validation_profiles.router)
app.include_router(workflow_productization.router)
app.include_router(workflows.router)
app.include_router(workflow_cases.router)
app.include_router(validation_scripts.router)
app.include_router(context_packs.router)
app.include_router(workflow_assets.router)
app.include_router(workflow_runs.router)
app.include_router(artifacts.router)
app.include_router(maintenance.router)
