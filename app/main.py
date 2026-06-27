from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import runtime
from app.controllers import artifact_controller, config_controller, project_controller, workflow_controller


app = FastAPI(title="Qwen Workflow Web MVP")


@app.on_event("startup")
async def startup() -> None:
    runtime.ensure_dirs()
    runtime.store.load_sync()
    runtime.mark_interrupted_runs()


@app.get("/")
async def index():
    return FileResponse(runtime.STATIC_DIR / "index.html")

@app.get("/workflow-designer")
async def workflow_designer():
    return FileResponse(runtime.STATIC_DIR / "workflow-designer.html")

app.mount("/static", StaticFiles(directory=runtime.STATIC_DIR), name="static")

app.include_router(config_controller.router)
app.include_router(project_controller.router)
app.include_router(workflow_controller.router)
app.include_router(artifact_controller.router)
