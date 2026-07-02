from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.core.locks import project_run_creation_lock
from app.core.metrics import metrics
from app.persistence.repositories import store as store_repository
from app.services.agent_session_service import default_agent_session_ids
from app.security.workspace_guard import PROJECT_WORKFLOW_DIR, LEGACY_WORKFLOW_DIR
from app.services import workflow_asset_service, workflow_config_service


ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_input", "cancelling"}
_RUN_CREATION_LOCKS: dict[int, asyncio.Lock] = {}


def _run_creation_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    return _RUN_CREATION_LOCKS.setdefault(id(loop), asyncio.Lock())


def _same_existing_project_path(left: str | None, right: str) -> bool:
    """Compare project paths without letting stale invalid store rows block new runs."""
    try:
        return str(runtime.resolve_project_path(left or str(runtime.ROOT))) == right
    except HTTPException:
        return False



def _cleanup_done_tasks() -> None:
    for task_run_id, task in list(runtime.running_tasks.items()):
        if task.done():
            runtime.running_tasks.pop(task_run_id, None)


def start_workflow_task(run_id: str, start_index: int = 0) -> None:
    _cleanup_done_tasks()
    task = asyncio.create_task(runtime.execute_workflow(run_id, start_index=start_index))
    runtime.running_tasks[run_id] = task
    task.add_done_callback(lambda _: runtime.running_tasks.pop(run_id, None))


def latest_session_run(data: dict, session_id: str) -> dict | None:
    runs = [run for run in data.get("runs", []) if run.get("session_id") == session_id]
    if not runs:
        return None
    return sorted(runs, key=lambda run: run.get("created_at", ""), reverse=True)[0]


def _runs_roots(project_path: str | Path) -> list[Path]:
    project = Path(project_path)
    roots = [project / PROJECT_WORKFLOW_DIR / "runs"]
    legacy = project / LEGACY_WORKFLOW_DIR / "runs"
    if legacy.exists():
        roots.append(legacy)
    return roots


def _candidate_run_state_paths(data: dict, *, run_id: str | None = None, session_id: str | None = None) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for session in data.get("sessions", []):
        if session_id and session.get("id") != session_id:
            continue
        try:
            project_path = runtime.resolve_project_path(session.get("project_path") or str(runtime.ROOT))
        except HTTPException:
            continue
        candidates: list[Path] = []
        for runs_root in _runs_roots(project_path):
            if not runs_root.exists():
                continue
            if run_id:
                candidates.append(runs_root / f"session-{session.get('id')}" / f"run-{run_id}" / ".workflow" / "state.json")
                candidates.extend(runs_root.glob(f"session-*/run-{run_id}/.workflow/state.json"))
            else:
                candidates.extend((runs_root / f"session-{session.get('id')}").glob("run-*/.workflow/state.json"))
        for path in candidates:
            key = str(path)
            if key not in seen and path.exists():
                seen.add(key)
                paths.append(path)
    return paths


def _normalize_rehydrated_run(run: dict, state_path: Path, session: dict | None) -> dict:
    now = runtime.utc_now()
    run = dict(run)
    run["workspace"] = str(state_path.parent.parent)
    if session:
        run.setdefault("session_id", session.get("id"))
        run.setdefault("project_path", session.get("project_path"))
        run.setdefault("qwen_session_id", session.get("qwen_session_id") or session.get("id"))
        run.setdefault(
            "agent_session_ids",
            session.get("agent_session_ids") or default_agent_session_ids(session.get("id"), session.get("qwen_session_id") or session.get("id")),
        )
    run.setdefault("status", "failed")
    run.setdefault("error", None)
    run.setdefault("error_code", None)
    run.setdefault("project_path", str(Path(run["workspace"]).parents[3]) if len(Path(run["workspace"]).parents) >= 4 else str(runtime.ROOT))
    run.setdefault("workflow_id", "")
    run.setdefault("workflow_folder", "")
    run.setdefault("workflow_name", run.get("workflow_id") or "")
    run.setdefault("skill_root", "")
    run.setdefault("test_command", None)
    run.setdefault("steps", [])
    run.setdefault("artifacts", [])
    run.setdefault("timeline", [])
    run.setdefault("created_at", now)
    run.setdefault("updated_at", now)
    run.setdefault("started_at", None)
    run.setdefault("ended_at", None)
    if not isinstance(run.get("agent_session_ids"), dict):
        run["agent_session_ids"] = default_agent_session_ids(run.get("session_id"), run.get("qwen_session_id") or run.get("session_id"))
    for step in run.get("steps", []):
        step.setdefault("status", "pending")
        step.setdefault("started_at", None)
        step.setdefault("ended_at", None)
        step.setdefault("error", None)
        step.setdefault("error_code", None)
        step.setdefault("retry_count", 0)
        step.setdefault("events", [])
    return run


async def _rehydrate_runs_from_workspace(*, run_id: str | None = None, session_id: str | None = None) -> list[dict]:
    data = await store_repository.read()
    existing_ids = {run.get("id") for run in data.get("runs", [])}
    recovered: list[dict] = []
    for state_path in _candidate_run_state_paths(data, run_id=run_id, session_id=session_id):
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        if run_id and raw.get("id") != run_id:
            continue
        if raw.get("id") in existing_ids:
            continue
        session = next((item for item in data.get("sessions", []) if item.get("id") == raw.get("session_id")), None)
        if session_id and raw.get("session_id") != session_id:
            continue
        run = _normalize_rehydrated_run(raw, state_path, session)
        await store_repository.mutate(lambda store, item=run: store["runs"].insert(0, item) if not any(r.get("id") == item["id"] for r in store.get("runs", [])) else None)
        recovered.append(run)
        existing_ids.add(run["id"])
    for run in recovered:
        await runtime.refresh_artifacts(run["id"])
        await runtime.log(run, "workflow: recovered run state from workspace")
    return recovered


async def get_latest_run_for_session(session_id: str) -> dict | None:
    data = await store_repository.read()
    if not any(session["id"] == session_id for session in data.get("sessions", [])):
        raise HTTPException(status_code=404, detail="Session not found")
    latest = latest_session_run(data, session_id)
    if latest:
        return latest
    recovered = await _rehydrate_runs_from_workspace(session_id=session_id)
    if recovered:
        data = await store_repository.read()
        return latest_session_run(data, session_id)
    return None


async def create_workflow_run(session_id: str, body: runtime.CreateRunRequest) -> dict:
    _cleanup_done_tasks()
    async with _run_creation_lock():
        data = await store_repository.read()
        session = next((session for session in data["sessions"] if session["id"] == session_id), None)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        project_path = str(runtime.resolve_project_path(body.project_path or session.get("project_path") or str(runtime.ROOT)))
        workflow_id = body.workflow_id or workflow_config_service.SYSTEM_WORKFLOW_ID
        try:
            workflow = await workflow_config_service.get_workflow(workflow_id, project_path=project_path)
        except TypeError as exc:
            if "project_path" not in str(exc) and "positional" not in str(exc):
                raise
            workflow = await workflow_config_service.get_workflow(workflow_id)
        workflow = workflow_asset_service.apply_contracts_to_workflow(workflow, project_path)
        async with project_run_creation_lock(project_path):
            data = await store_repository.read()
            active_run = next(
                (
                    run
                    for run in data.get("runs", [])
                    if run.get("status") in ACTIVE_RUN_STATUSES
                    and _same_existing_project_path(run.get("project_path"), project_path)
                ),
                None,
            )
            if active_run:
                return active_run
            requirement = body.requirement
            if not requirement:
                messages = [
                    msg
                    for msg in data["messages"]
                    if msg["session_id"] == session_id
                    and msg["role"] == "user"
                    and msg.get("kind", "requirement") == "requirement"
                ]
                requirement = messages[-1]["content"] if messages else None
            if not requirement:
                raise HTTPException(status_code=400, detail="Requirement is required")

            steps = runtime.initial_steps(workflow.get("steps", []))
            if not steps:
                raise HTTPException(status_code=400, detail="Workflow has no enabled steps.")

            run_id = str(uuid.uuid4())
            project_dir = Path(project_path)
            run_dir = project_dir / PROJECT_WORKFLOW_DIR / "runs" / f"session-{session_id}" / f"run-{run_id}"
            (run_dir / "output").mkdir(parents=True, exist_ok=True)
            (run_dir / "input").mkdir(parents=True, exist_ok=True)
            (run_dir / ".workflow").mkdir(parents=True, exist_ok=True)
            runtime.write_text(run_dir / "requirement.md", requirement)
            runtime.write_text(run_dir / ".workflow" / "run-log.md", "")
            run = {
                "id": run_id,
                "session_id": session_id,
                "qwen_session_id": session.get("qwen_session_id") or session_id,
                "agent_session_ids": session.get("agent_session_ids")
                or default_agent_session_ids(session_id, session.get("qwen_session_id") or session_id),
                "status": "queued",
                "error": None,
                "workspace": str(run_dir),
                "project_path": project_path,
                "workflow_id": workflow["id"],
                "workflow_folder": workflow.get("folderName") or workflow["id"],
                "workflow_name": workflow.get("name") or workflow["id"],
                "skill_root": workflow.get("skillRoot") or "",
                "test_command": body.test_command,
                "validation_script": body.validation_script,
                "steps": steps,
                "artifacts": [],
                "timeline": [],
                "created_at": runtime.utc_now(),
                "updated_at": runtime.utc_now(),
                "started_at": None,
                "ended_at": None,
            }
            runtime.write_text(run_dir / ".workflow" / "state.json", json.dumps(run, indent=2, ensure_ascii=False))
            await store_repository.mutate(lambda d: (d["runs"].insert(0, run), run)[1])
            await runtime.refresh_artifacts(run_id)
            metrics.increment("workflow.started")
            start_workflow_task(run_id)
            return run


async def get_run(run_id: str) -> dict:
    _cleanup_done_tasks()
    try:
        return await runtime.get_run_record(run_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    recovered = await _rehydrate_runs_from_workspace(run_id=run_id)
    if recovered:
        return await runtime.get_run_record(run_id)
    raise HTTPException(status_code=404, detail="Run not found")


async def retry_run(run_id: str, body: runtime.RetryRunRequest | None = None) -> dict:
    body = body or runtime.RetryRunRequest()
    run = await get_run(run_id)
    active_task = runtime.running_tasks.get(run_id)
    if active_task and not active_task.done():
        raise HTTPException(status_code=400, detail="This run is still running. Wait for it to finish before retrying.")
    data = await store_repository.read()
    run_project_path = str(runtime.resolve_project_path(run.get("project_path") or str(runtime.ROOT)))
    active_other = next(
        (
            item
            for item in data.get("runs", [])
            if item.get("id") != run_id
            and item.get("status") in ACTIVE_RUN_STATUSES
            and _same_existing_project_path(item.get("project_path"), run_project_path)
        ),
        None,
    )
    if active_other:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_ALREADY_RUNNING",
                "message": "This project already has an active workflow run.",
                "details": {"projectPath": run_project_path, "runId": active_other["id"], "status": active_other.get("status")},
            },
        )
    step_keys = [step["key"] for step in run["steps"]]
    if body.step_key:
        if body.step_key not in step_keys:
            raise HTTPException(status_code=400, detail=f"Unknown step: {body.step_key}")
        start_index = step_keys.index(body.step_key)
    else:
        failed_index = next((index for index, step in enumerate(run["steps"]) if step["status"] in {"failed", "waiting_input"}), None)
        start_index = failed_index if failed_index is not None else 0
    await runtime.reset_retry_counts_from(run_id, start_index)
    target_key = step_keys[start_index] if step_keys else ""
    if target_key:
        await runtime.record_step_event(
            run_id,
            target_key,
            "manual_retry",
            f"Manual retry requested from {target_key}; retry counters were reset from this step.",
            {"target_step": target_key, "start_index": start_index},
        )
    await runtime.reset_steps_from(run_id, start_index)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def terminate_run(run_id: str) -> dict:
    run = await get_run(run_id)
    def mark_cancelling(item):
        item["status"] = "cancelling"
        item["updated_at"] = runtime.utc_now()

    await runtime.update_run(run_id, mark_cancelling)
    task = runtime.running_tasks.get(run_id)
    proc = runtime.running_processes.get(run_id)
    if proc and proc.returncode is None:
        proc.terminate()
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    else:
        def cancel(item):
            item["status"] = "cancelled"
            item["error"] = "Workflow cancelled by user."
            item["ended_at"] = runtime.utc_now()
            item["updated_at"] = runtime.utc_now()
            for step in item.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "cancelled"
                    step["error"] = item["error"]
                    step["ended_at"] = runtime.utc_now()

        await runtime.update_run(run_id, cancel)
        await runtime.refresh_artifacts(run_id)
    await runtime.log(run, "workflow: terminate requested")
    return await get_run(run_id)


async def submit_answers(run_id: str, body: runtime.SubmitAnswersRequest) -> dict:
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Answer content is required")
    run = await get_run(run_id)
    if run.get("status") != "waiting_input":
        raise HTTPException(status_code=400, detail="This run is not waiting for user input.")
    active_task = runtime.running_tasks.get(run_id)
    if active_task and not active_task.done():
        raise HTTPException(status_code=400, detail="This run is still running. Wait for it to pause before continuing.")

    steps = run.get("steps", [])
    step_keys = [step["key"] for step in steps]
    if body.step_key and body.step_key in step_keys:
        start_index = step_keys.index(body.step_key)
        step_key = body.step_key
    else:
        waiting_index = next((index for index, step in enumerate(steps) if step.get("status") == "waiting_input"), None)
        if waiting_index is None:
            raise HTTPException(status_code=400, detail="No waiting step was found for this run.")
        start_index = waiting_index
        step_key = steps[waiting_index]["key"]

    run_dir = Path(run["workspace"])
    answers_path = run_dir / "input" / "answers.md"
    previous = runtime.read_text(answers_path)
    entry = (
        f"## Reply for {step_key}\n\n"
        f"Submitted at: {runtime.utc_now()}\n\n"
        f"{content}\n\n"
    )
    runtime.write_text(answers_path, previous + ("\n" if previous.strip() else "") + entry)
    await runtime.append_session_message(run["session_id"], "user", content, kind="answer")
    await runtime.log(run, f"{step_key}: user submitted reply")
    await runtime.refresh_artifacts(run_id)
    await runtime.reset_steps_from(run_id, start_index)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def submit_guidance(run_id: str, body: runtime.SubmitGuidanceRequest) -> dict:
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Guidance content is required")
    run = await get_run(run_id)
    active_task = runtime.running_tasks.get(run_id)
    is_running = bool(active_task and not active_task.done())

    steps = run.get("steps", [])
    step_keys = [step["key"] for step in steps]
    if body.step_key not in step_keys:
        raise HTTPException(status_code=400, detail=f"Unknown step: {body.step_key}")
    start_index = step_keys.index(body.step_key)

    run_dir = Path(run["workspace"])
    guidance_path = run_dir / "input" / "guidance.md"
    previous = runtime.read_text(guidance_path)
    entry = (
        f"## Guidance for {body.step_key}\n\n"
        f"Submitted at: {runtime.utc_now()}\n\n"
        f"{content}\n\n"
    )
    runtime.write_text(guidance_path, previous + ("\n" if previous.strip() else "") + entry)
    await runtime.log(run, f"{body.step_key}: user added guidance")
    await runtime.refresh_artifacts(run_id)
    if is_running:
        return await get_run(run_id)
    await runtime.reset_steps_from(run_id, start_index)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def simulate_question(run_id: str) -> dict:
    run = await get_run(run_id)
    active_task = runtime.running_tasks.get(run_id)
    if active_task and not active_task.done():
        raise HTTPException(status_code=400, detail="This run is still running. Wait for it to pause before simulating input.")

    steps = run.get("steps", [])
    target_index = next((index for index, step in enumerate(steps) if step.get("status") in {"failed", "waiting_input"}), None)
    if target_index is None:
        target_index = next((index for index, step in enumerate(steps) if step.get("status") == "pending"), None)
    if target_index is None:
        target_index = max(len(steps) - 1, 0)
    step_key = steps[target_index]["key"]

    run_dir = Path(run["workspace"])
    question = (
        "## Test Interaction\n\n"
        "This is a simulated workflow question used to verify that a run can pause, "
        "show a question, and continue after the user replies.\n\n"
        "- Reply with the missing information, such as language, test framework, or requirement details.\n"
    )
    runtime.write_text(run_dir / "input" / "questions.md", question)
    await runtime.log(run, f"{step_key}: simulated user-input request")

    def apply(item):
        item["status"] = "waiting_input"
        item["error"] = f"{step_key}: simulated question. See input/questions.md."
        item["ended_at"] = runtime.utc_now()
        item["updated_at"] = runtime.utc_now()
        for index, step in enumerate(item.get("steps", [])):
            if index == target_index:
                step["status"] = "waiting_input"
                step["error"] = item["error"]
                step["ended_at"] = runtime.utc_now()
            elif index > target_index and step.get("status") == "running":
                step["status"] = "pending"
                step["error"] = None
                step["started_at"] = None
                step["ended_at"] = None

    await runtime.update_run(run_id, apply)
    await runtime.refresh_artifacts(run_id)
    updated = await get_run(run_id)
    await runtime.bus.publish(run_id, {"type": "waiting_input", "error": updated.get("error")})
    return updated


async def get_steps(run_id: str) -> list[dict]:
    return (await get_run(run_id))["steps"]


async def get_artifacts(run_id: str) -> list[dict]:
    return (await get_run(run_id))["artifacts"]
