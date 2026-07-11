from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import tempfile
import uuid
from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path

from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.core.locks import project_run_creation_lock
from app.core.metrics import metrics
from app.persistence.repositories import store as store_repository
from app.services.agent_session_service import default_agent_session_ids
from app.security.workspace_guard import PROJECT_WORKFLOW_DIR, LEGACY_WORKFLOW_DIR
from app.services import workflow_asset_service, workflow_config_service
from app.workflow_runtime.run_profiles import apply_run_profile, normalize_run_profile
from app.workflow_runtime.thinking import apply_thinking_level_to_steps, normalize_thinking_level
from app.workflow_runtime.run_diff import write_baseline_snapshot, build_run_diff
from app.workflow_runtime.failure_classifier import classify_run_failures
from app.workflow_runtime.run_console import build_run_console
from app.workflow_runtime.benchmark import summarize_runs
from app.workflow_runtime.patch_approval import patch_preview, write_patch_artifacts, apply_patch
from app.workflow_runtime.versioning import build_version_metadata
from app.workflow_runtime.run_artifacts import read_run_artifact_index
from app.workflow_runtime.run_consistency import check_run_consistency
from app.workflow_runtime.artifact_policy import filter_artifacts, compact_run_diagnostics
from app.services.run_overview_service import build_run_overview
from app.workflow_engine.state_machine import append_transition
from app.workflow_runtime.artifact_repair import repair_run_artifacts
from app.workflow_runtime.repair_policy import policy_for_failure
from app.workflow_runtime.recovery_counters import increment_recovery_counter
from app.workflow_runtime.risk_engine import assess_risk
from app.workflow_runtime.model_capabilities import resolve_model_capability
from app.workflow_runtime.validators import detect_validator_plans
from app.workflow_runtime.scope_control import analyze_scope_delta
from app.workflow_runtime.task_checkpoints import restore_task_checkpoint
from app.workflow_runtime.validation_contract import ValidationContractError, build_validation_contract
from app.workflow_runtime.run_lifecycle import (
    ACTIVE_RUN_STATUSES,
    cleanup_stale_project_lock,
    clear_project_lock,
    find_active_run_for_project,
    mark_cancel_requested,
    recover_stale_active_runs_for_project,
    read_project_lock,
    write_project_lock,
)
from app.security.isolated_workspace import create_isolated_project_copy
from app.services.context_pack_service import render_context_pack_prompt
from app.stores import FileArtifactStore, FileLockStore, FileRunStore, FileStepStore
from app.agents.process_supervisor import terminate_async_process_tree


_RUN_CREATION_LOCKS: dict[int, asyncio.Lock] = {}
_RUN_STORE = FileRunStore(read=store_repository.read, mutate=store_repository.mutate)
_STEP_STORE = FileStepStore(_RUN_STORE)
_ARTIFACT_STORE = FileArtifactStore(_RUN_STORE)
_LOCK_STORE = FileLockStore()



def _run_creation_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    return _RUN_CREATION_LOCKS.setdefault(id(loop), asyncio.Lock())




async def _clear_persisted_project_lock(run_id: str, run: dict | None = None) -> dict:
    latest = run or await runtime.get_run_record(run_id)
    clear_project_lock(latest)
    updated = await runtime.update_run(run_id, lambda item: item.update({"project_lock": None}))
    return updated or latest


async def _persist_project_lock(run_id: str, run: dict) -> dict:
    lock = write_project_lock(run)
    if lock:
        latest = await runtime.update_run(run_id, lambda item: item.update({"project_lock": lock}))
        return latest or run
    return run


def default_patch_mode_for_agent(agent_name: str | None) -> str:
    """Write to the selected project by default for local workflow runs.

    Review and dry-run isolation remain available through ``patchMode`` or the
    ``AIWF_DEFAULT_PATCH_MODE`` environment variable.  The UI does not expose a
    patch-mode selector, so defaulting real agents to ``review`` unexpectedly
    redirected their cwd into ``.ai-workflow/.../isolated-workspace`` and left
    successful generated files outside the project selected by the user.
    """
    override = os.environ.get("AIWF_DEFAULT_PATCH_MODE")
    if override:
        return override.strip().lower().replace("-", "_")
    return "auto_apply"

def _same_existing_project_path(left: str | None, right: str) -> bool:
    """Compare project paths without letting stale invalid store rows block new runs."""
    try:
        return str(runtime.resolve_project_path(left or str(runtime.ROOT))) == right
    except HTTPException:
        return False



async def _recover_stale_project_active_runs(project_path: str) -> list[dict]:
    recovered = await store_repository.mutate(lambda data: recover_stale_active_runs_for_project(data, project_path))
    for run in recovered:
        try:
            clear_project_lock(run)
            run["project_lock"] = None
            run_dir = Path(run.get("workspace") or "")
            if run_dir:
                (run_dir / ".workflow").mkdir(parents=True, exist_ok=True)
                runtime.write_text(run_dir / ".workflow" / "state.json", json.dumps(run, indent=2, ensure_ascii=False))
                previous = runtime.read_text(run_dir / ".workflow" / "run-log.md")
                runtime.write_text(
                    run_dir / ".workflow" / "run-log.md",
                    previous
                    + ("\n" if previous.strip() else "")
                    + f"{runtime.utc_now()} workflow: stale active run recovered; owner process is no longer alive.\n",
                )
                await runtime.refresh_artifacts(run.get("id"))
        except Exception:
            continue
    return recovered


def _cleanup_done_tasks() -> None:
    for task_run_id, task in list(runtime.running_tasks.items()):
        if task.done():
            runtime.running_tasks.pop(task_run_id, None)


async def _execute_with_run_timeout(run_id: str, start_index: int = 0) -> None:
    run = await runtime.get_run_record(run_id)
    timeout = int(run.get("run_timeout_sec") or 0)
    if timeout > 0:
        try:
            await asyncio.wait_for(runtime.execute_workflow(run_id, start_index=start_index), timeout=timeout)
        except asyncio.TimeoutError:
            proc = runtime.running_processes.get(run_id)
            if proc and proc.returncode is None:
                await terminate_async_process_tree(proc, grace_sec=2.0)
            message = f"Workflow timed out after {timeout} seconds."
            await runtime.update_run(
                run_id,
                lambda item: item.update({
                    "status": "failed",
                    "error": message,
                    "error_code": "TIMEOUT",
                    "ended_at": runtime.utc_now(),
                    "updated_at": runtime.utc_now(),
                }),
            )
            latest = await runtime.get_run_record(run_id)
            await runtime.log(latest, f"workflow: {message}")
            await runtime.refresh_artifacts(run_id)
            await runtime.bus.publish(run_id, {"type": "failed", "error": message})
    else:
        await runtime.execute_workflow(run_id, start_index=start_index)


async def _finalize_workflow_task(run_id: str) -> None:
    try:
        latest = await runtime.get_run_record(run_id)
    except HTTPException:
        runtime.running_tasks.pop(run_id, None)
        return
    if latest.get("status") in {"done", "failed", "cancelled"}:
        await _clear_persisted_project_lock(run_id, latest)
    runtime.running_tasks.pop(run_id, None)


def start_workflow_task(run_id: str, start_index: int = 0) -> None:
    _cleanup_done_tasks()
    task = asyncio.create_task(_execute_with_run_timeout(run_id, start_index=start_index))
    runtime.running_tasks[run_id] = task

    def _done(_: asyncio.Task) -> None:
        try:
            asyncio.create_task(_finalize_workflow_task(run_id))
        except RuntimeError:
            runtime.running_tasks.pop(run_id, None)

    task.add_done_callback(_done)


def latest_session_run(data: dict, session_id: str) -> dict | None:
    # Compatibility helper for older tests; runtime code uses _RUN_STORE.
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
    latest = await _RUN_STORE.latest_for_session(session_id)
    if latest:
        return latest
    recovered = await _rehydrate_runs_from_workspace(session_id=session_id)
    if recovered:
        return await _RUN_STORE.latest_for_session(session_id)
    return None


async def create_workflow_run(session_id: str, body: runtime.CreateRunRequest) -> dict:
    _cleanup_done_tasks()
    async with _run_creation_lock():
        data = await store_repository.read()
        session = next((session for session in data["sessions"] if session["id"] == session_id), None)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        project_path = str(runtime.resolve_project_path(body.project_path or session.get("project_path") or str(runtime.ROOT)))
        if body.skill or body.config:
            workflow = workflow_asset_service.load_ad_hoc_workflow_asset(
                skill=body.skill,
                config=body.config,
                project_path=project_path,
                workflow_id=body.workflow_id,
            )
        else:
            workflow_id = body.workflow_id or workflow_config_service.SYSTEM_WORKFLOW_ID
            try:
                workflow = await workflow_config_service.get_workflow(workflow_id, project_path=project_path)
            except TypeError as exc:
                if "project_path" not in str(exc) and "positional" not in str(exc):
                    raise
                workflow = await workflow_config_service.get_workflow(workflow_id)
            workflow = workflow_asset_service.apply_contracts_to_workflow(workflow, project_path)
        async with project_run_creation_lock(project_path):
            await _recover_stale_project_active_runs(project_path)
            data = await store_repository.read()
            cleanup_stale_project_lock(project_path, data)
            active_run = find_active_run_for_project(data, project_path)
            if active_run:
                return active_run
            project_lock = read_project_lock(project_path)
            if project_lock:
                # A persisted lock can survive a crash before startup recovery runs.
                # Re-read after cleanup, and only block if it still points to an active run.
                data = await store_repository.read()
                cleanup_stale_project_lock(project_path, data)
                active_run = find_active_run_for_project(data, project_path)
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

            context_pack = (body.context_pack or "").strip() or None
            if context_pack:
                requirement = requirement.rstrip() + "\n\n---\n\n" + render_context_pack_prompt(context_pack)

            run_profile = normalize_run_profile(body.run_profile)
            thinking_level_override = body.thinking_level is not None
            thinking_level = normalize_thinking_level(body.thinking_level, default="none")
            steps = apply_run_profile(runtime.initial_steps(workflow.get("steps", [])), run_profile)
            if thinking_level_override:
                steps = apply_thinking_level_to_steps(steps, thinking_level)
            if not steps:
                raise HTTPException(status_code=400, detail="Workflow has no enabled steps.")

            run_id = str(uuid.uuid4())
            original_project_path = project_path
            original_project_dir = Path(project_path)
            risk = assess_risk(requirement, project_path=original_project_path)
            recommended = risk.get("recommended") or {}
            run_dir = original_project_dir / PROJECT_WORKFLOW_DIR / "runs" / f"session-{session_id}" / f"run-{run_id}"
            (run_dir / "output").mkdir(parents=True, exist_ok=True)
            (run_dir / "input").mkdir(parents=True, exist_ok=True)
            (run_dir / ".workflow").mkdir(parents=True, exist_ok=True)
            patch_mode = (body.patch_mode or recommended.get("patch_mode") or default_patch_mode_for_agent(body.agent)).strip().lower().replace("-", "_")
            if patch_mode not in {"auto_apply", "review", "dry_run"}:
                raise HTTPException(status_code=400, detail="patchMode must be auto_apply, review, or dry_run")
            effective_project_path = project_path
            isolated_project_path = None
            if patch_mode in {"review", "dry_run"}:
                isolated_project_path = str(create_isolated_project_copy(original_project_dir, run_dir / ".workflow" / "isolated-workspace"))
                effective_project_path = isolated_project_path
            runtime.write_text(run_dir / "requirement.md", requirement)
            runtime.write_text(run_dir / ".workflow" / "run-log.md", "")
            approval_mode = (body.approval_mode or recommended.get("approval_mode") or "fully_automatic").strip().lower()
            if approval_mode not in {"fully_automatic", "milestones", "review_before_apply", "plan_and_patch_only"}:
                raise HTTPException(status_code=400, detail="approvalMode must be fully_automatic, milestones, review_before_apply, or plan_and_patch_only")
            validator_plans = detect_validator_plans(original_project_path)
            model_capability = resolve_model_capability(run_profile)
            validation_required = bool(body.validation_script) or any(
                bool((step.get("config") or {}).get("requiresValidationScript") or step.get("requires_validation_script"))
                for step in steps
            )
            try:
                validation_contract = build_validation_contract(
                    original_project_dir,
                    body.validation_script,
                    required=validation_required,
                    timeout_seconds=int(os.environ.get("AIWF_VALIDATION_TIMEOUT_SEC", "300")),
                )
            except ValidationContractError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            run = {
                "id": run_id,
                "session_id": session_id,
                "qwen_session_id": session.get("qwen_session_id") or session_id,
                "agent_session_ids": session.get("agent_session_ids")
                or default_agent_session_ids(session_id, session.get("qwen_session_id") or session_id),
                "status": "queued",
                "error": None,
                "run_owner": runtime.current_run_owner(),
                "workspace": str(run_dir),
                "project_path": effective_project_path,
                "original_project_path": original_project_path,
                "isolated_project_path": isolated_project_path,
                "patch_mode": patch_mode,
                "patch_status": "pending" if patch_mode in {"review", "dry_run"} else "not_required",
                "workflow_id": workflow["id"],
                "workflow_folder": workflow.get("folderName") or workflow["id"],
                "workflow_name": workflow.get("name") or workflow["id"],
                "skill_root": workflow.get("skillRoot") or "",
                "agent": (body.agent.strip() if body.agent else None),
                "test_command": body.test_command,
                "validation_script": body.validation_script,
                "validation_contract": validation_contract,
                "run_profile": run_profile,
                "thinking_level": thinking_level,
                "thinking_level_override": thinking_level_override,
                "run_timeout_sec": body.run_timeout_sec,
                "workflow_version": body.workflow_version or workflow.get("version") or workflow.get("updated_at") or workflow["id"],
                "prompt_version": body.prompt_version or "current",
                "contract_version": body.contract_version or "current",
                "context_pack": context_pack,
                "approval_mode": approval_mode,
                "approval_state": (
                    "not_required"
                    if approval_mode == "fully_automatic" or (approval_mode == "milestones" and not risk.get("high_risk"))
                    else "pending"
                ),
                "risk_assessment": risk,
                "model_capability": model_capability,
                "validator_plans": validator_plans,
                "benchmark_id": body.benchmark_id,
                "steps": steps,
                "tasks": [],
                "role_session_ids": {},
                "artifacts": [],
                "timeline": [],
                "validation_results": [],
                "file_changes": [],
                "checkpoints": [],
                "task_checkpoints": [],
                "transitions": [],
                "phase": "queued",
                "created_at": runtime.utc_now(),
                "updated_at": runtime.utc_now(),
                "started_at": None,
                "ended_at": None,
            }
            append_transition(run, kind="run", source=None, target="queued", reason="run created")
            write_baseline_snapshot(run, run_dir)
            run["checkpoints"].append({
                "id": "baseline",
                "step_key": None,
                "status": "ready",
                "created_at": runtime.utc_now(),
                "path": ".workflow/project-snapshot-before.json",
                "description": "Project state before workflow execution.",
            })
            runtime.write_text(run_dir / ".workflow" / "version-metadata.json", json.dumps(build_version_metadata(run), indent=2, ensure_ascii=False))
            if patch_mode in {"review", "dry_run"}:
                write_patch_artifacts(run)
            run["project_lock"] = write_project_lock(run)
            runtime.write_text(run_dir / ".workflow" / "state.json", json.dumps(run, indent=2, ensure_ascii=False))
            await store_repository.mutate(lambda d: (d["runs"].insert(0, run), run)[1])
            await runtime.refresh_artifacts(run_id)
            metrics.increment("workflow.started")
            start_workflow_task(run_id)
            return run


async def get_run_debug_bundle(run_id: str) -> dict:
    run = await get_run(run_id)
    failed_step = next((step for step in run.get("steps", []) if step.get("status") in {"failed", "waiting_input", "cancelled"}), None)
    retry_total = sum(int(step.get("retry_count") or 0) for step in run.get("steps", []))
    artifact_paths = [str(item.get("path") or item.get("name") or "") for item in run.get("artifacts", []) if item]
    bundle = {
        "schema": "aiwf.debug-bundle.v1",
        "runId": run.get("id"),
        "sessionId": run.get("session_id"),
        "workflow": run.get("workflow_id") or run.get("workflow_name"),
        "status": run.get("status"),
        "failedStep": (failed_step or {}).get("key"),
        "failureType": (failed_step or {}).get("error_code") or run.get("error_code"),
        "retryCount": retry_total,
        "patchMode": run.get("patch_mode"),
        "patchStatus": run.get("patch_status"),
        "projectPath": run.get("original_project_path") or run.get("project_path"),
        "effectiveProjectPath": run.get("project_path"),
        "workspace": run.get("workspace"),
        "lastError": run.get("error") or (failed_step or {}).get("error"),
        "artifactCount": len(artifact_paths),
        "artifacts": artifact_paths[:50],
        "createdAt": run.get("created_at"),
        "updatedAt": run.get("updated_at"),
        "endedAt": run.get("ended_at"),
    }
    return bundle


async def export_run_bundle(run_id: str) -> Path:
    """Create a self-contained run bundle for debugging, sharing, or replay."""
    run = await get_run(run_id)
    run_dir = Path(run["workspace"])
    export_root = Path(tempfile.mkdtemp(prefix=f"aiwf-export-{run_id}-"))
    bundle_path = export_root / f"run-{run_id}-bundle.zip"
    manifest = {
        "schema": "aiwf.run-bundle.v1",
        "run_id": run.get("id"),
        "session_id": run.get("session_id"),
        "workflow_id": run.get("workflow_id"),
        "workflow_name": run.get("workflow_name"),
        "project_path": run.get("project_path"),
        "status": run.get("status"),
        "requirement": runtime.read_text(run_dir / "requirement.md"),
        "validation_script": run.get("validation_script"),
        "test_command": run.get("test_command"),
        "run_profile": run.get("run_profile"),
        "thinking_level": run.get("thinking_level"),
    }
    with ZipFile(bundle_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("bundle-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("run.json", json.dumps(run, indent=2, ensure_ascii=False))
        if run_dir.exists():
            for path in run_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, f"run-workspace/{path.relative_to(run_dir).as_posix()}")
    return bundle_path


async def replay_run(run_id: str, body: runtime.CreateRunRequest | None = None) -> dict:
    """Replay a previous run by creating a fresh run with the same requirement/workflow/project by default."""
    source = await get_run(run_id)
    source_dir = Path(source["workspace"])
    override = body or runtime.CreateRunRequest()
    replay_body = runtime.CreateRunRequest(
        requirement=override.requirement or runtime.read_text(source_dir / "requirement.md"),
        test_command=override.test_command if override.test_command is not None else source.get("test_command"),
        validation_script=override.validation_script if override.validation_script is not None else source.get("validation_script"),
        project_path=override.project_path or source.get("original_project_path") or source.get("project_path"),
        workflow_id=override.workflow_id or source.get("workflow_id"),
        agent=override.agent or source.get("agent"),
        runProfile=override.run_profile or source.get("run_profile"),
        thinkingLevel=override.thinking_level if override.thinking_level is not None else source.get("thinking_level"),
        runTimeoutSec=override.run_timeout_sec if override.run_timeout_sec is not None else source.get("run_timeout_sec"),
        patchMode=override.patch_mode or source.get("patch_mode"),
        workflowVersion=override.workflow_version or source.get("workflow_version"),
        promptVersion=override.prompt_version or source.get("prompt_version"),
        contractVersion=override.contract_version or source.get("contract_version"),
        contextPack=override.context_pack or source.get("context_pack"),
    )
    replay = await create_workflow_run(source["session_id"], replay_body)
    await runtime.log(replay, f"workflow: replayed from run {run_id}")
    await runtime.record_step_event(replay["id"], replay["steps"][0]["key"] if replay.get("steps") else "replay", "replay", f"Replayed from run {run_id}", {"source_run_id": run_id})
    return await get_run(replay["id"])


async def get_run(run_id: str) -> dict:
    _cleanup_done_tasks()
    run = await _RUN_STORE.get(run_id)
    if run:
        return run
    recovered = await _rehydrate_runs_from_workspace(run_id=run_id)
    if recovered:
        run = await _RUN_STORE.get(run_id)
        if run:
            return run
    raise HTTPException(status_code=404, detail="Run not found")


async def retry_run(run_id: str, body: runtime.RetryRunRequest | None = None) -> dict:
    body = body or runtime.RetryRunRequest()
    run = await get_run(run_id)
    active_task = runtime.running_tasks.get(run_id)
    if active_task and not active_task.done():
        raise HTTPException(status_code=400, detail="This run is still running. Wait for it to finish before retrying.")
    run_project_path = str(runtime.resolve_project_path(run.get("original_project_path") or run.get("project_path") or str(runtime.ROOT)))
    await _recover_stale_project_active_runs(run_project_path)
    data = await store_repository.read()
    cleanup_stale_project_lock(run_project_path, data)
    active_other = find_active_run_for_project(data, run_project_path, exclude_run_id=run_id)
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
    latest = await get_run(run_id)
    latest = await _persist_project_lock(run_id, latest)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def terminate_run(run_id: str) -> dict:
    run = await get_run(run_id)
    def mark_cancelling(item):
        mark_cancel_requested(item)

    await runtime.update_run(run_id, mark_cancelling)
    task = runtime.running_tasks.get(run_id)
    proc = runtime.running_processes.get(run_id)
    if proc and proc.returncode is None:
        await terminate_async_process_tree(proc, grace_sec=2.0)
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
        latest = await get_run(run_id)
        await _clear_persisted_project_lock(run_id, latest)
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
    latest = await get_run(run_id)
    latest = await _persist_project_lock(run_id, latest)
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
    latest = await get_run(run_id)
    latest = await _persist_project_lock(run_id, latest)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def _assert_not_active(run_id: str) -> dict:
    run = await get_run(run_id)
    active_task = runtime.running_tasks.get(run_id)
    if active_task and not active_task.done():
        raise HTTPException(status_code=400, detail="This run is still running. Stop it before manual step control.")
    return run


async def _step_index_or_400(run: dict, step_key: str) -> int:
    for index, step in enumerate(run.get("steps", [])):
        if step.get("key") == step_key:
            return index
    raise HTTPException(status_code=400, detail=f"Unknown step: {step_key}")


async def skip_step(run_id: str, body: runtime.StepControlRequest) -> dict:
    run = await _assert_not_active(run_id)
    step_index = await _step_index_or_400(run, body.step_key)
    reason = (body.reason or "Skipped manually by user.").strip()

    def apply(item):
        item["status"] = "waiting_input" if any(s.get("status") == "waiting_input" for s in item.get("steps", [])) else item.get("status", "failed")
        item["updated_at"] = runtime.utc_now()
        for index, step in enumerate(item.get("steps", [])):
            if index == step_index:
                step["status"] = "skipped"
                step["error"] = reason
                step["error_code"] = None
                step["ended_at"] = runtime.utc_now()
            elif index > step_index and step.get("status") in {"running", "failed", "waiting_input"}:
                step["status"] = "pending"
                step["error"] = None
                step["error_code"] = None
                step["started_at"] = None
                step["ended_at"] = None

    await runtime.update_run(run_id, apply)
    await runtime.record_step_event(run_id, body.step_key, "manual_skip", reason, {"target_step": body.step_key})
    await runtime.refresh_artifacts(run_id)
    return await get_run(run_id)


async def mark_step_passed(run_id: str, body: runtime.StepControlRequest) -> dict:
    run = await _assert_not_active(run_id)
    step_index = await _step_index_or_400(run, body.step_key)
    reason = (body.reason or "Marked passed manually by user.").strip()

    def apply(item):
        item["updated_at"] = runtime.utc_now()
        for index, step in enumerate(item.get("steps", [])):
            if index == step_index:
                step["status"] = "passed"
                step["error"] = reason
                step["error_code"] = None
                step["ended_at"] = runtime.utc_now()
            elif index > step_index and step.get("status") in {"running", "failed", "waiting_input"}:
                step["status"] = "pending"
                step["error"] = None
                step["error_code"] = None
                step["started_at"] = None
                step["ended_at"] = None

    await runtime.update_run(run_id, apply)
    await runtime.record_step_event(run_id, body.step_key, "manual_pass", reason, {"target_step": body.step_key})
    await runtime.refresh_artifacts(run_id)
    return await get_run(run_id)


async def resume_run(run_id: str, body: runtime.StepControlRequest | None = None) -> dict:
    run = await _assert_not_active(run_id)
    step_keys = [step["key"] for step in run.get("steps", [])]
    if not step_keys:
        raise HTTPException(status_code=400, detail="Run has no steps to resume.")
    if body and body.step_key:
        start_index = await _step_index_or_400(run, body.step_key)
    elif run.get("restart_recoverable") and isinstance(run.get("recovery"), dict):
        start_index = max(0, min(int(run["recovery"].get("resume_index") or 0), len(step_keys) - 1))
    else:
        start_index = next((index for index, step in enumerate(run.get("steps", [])) if step.get("status") in {"pending", "failed", "waiting_input", "skipped"}), len(step_keys) - 1)
    target_key = step_keys[start_index]
    await runtime.record_step_event(run_id, target_key, "manual_resume", "Manual resume requested.", {"target_step": target_key, "start_index": start_index})
    await runtime.reset_steps_from(run_id, start_index)
    def clear_recovery(item):
        item["restart_recoverable"] = False
        item["recovery"] = None
        item["error"] = None
        item["error_code"] = None
    await runtime.update_run(run_id, clear_recovery)
    latest = await get_run(run_id)
    latest = await _persist_project_lock(run_id, latest)
    start_workflow_task(run_id, start_index=start_index)
    return await get_run(run_id)


async def execute_run_action(run_id: str, body: runtime.RunActionRequest) -> dict:
    action = str(body.action or "").strip().lower()
    if action == "retry_current":
        return await retry_run(run_id, runtime.RetryRunRequest(step_key=body.step_key))
    if action == "retry_fresh_session":
        def request_fresh(item):
            item["_fresh_agent_session_once"] = True
            increment_recovery_counter(item, "session_restarts")
            increment_recovery_counter(item, "manual_actions")
            item.setdefault("manual_actions", []).append({"action": action, "at": runtime.utc_now(), "reason": body.reason})
        await runtime.update_run(run_id, request_fresh)
        return await retry_run(run_id, runtime.RetryRunRequest(step_key=body.step_key))
    if action == "resume":
        control = runtime.StepControlRequest(step_key=body.step_key, reason=body.reason) if body.step_key else None
        return await resume_run(run_id, control)
    if action == "stop":
        return await terminate_run(run_id)
    if action == "keep_changes":
        run = await _assert_not_active(run_id)
        await runtime.record_step_event(run_id, body.step_key or "run", "keep_changes", body.reason or "Current project changes were kept.")
        return run
    if action == "rollback_task":
        run = await _assert_not_active(run_id)
        checkpoints = list(run.get("task_checkpoints") or [])
        checkpoint_id = body.step_key or (checkpoints[-1].get("id") if checkpoints else None)
        if not checkpoint_id:
            raise HTTPException(status_code=409, detail={"code": "ROLLBACK_REQUIRES_CHECKPOINT", "message": "No accepted task checkpoint is available."})
        result = restore_task_checkpoint(run, checkpoint_id, project_dir=Path(run.get("project_path") or ""))
        selected_index = next((index for index, row in enumerate(checkpoints) if row.get("id") == checkpoint_id), len(checkpoints) - 1)
        selected = checkpoints[selected_index] if checkpoints else {}
        accepted_ids = {str(row.get("task_id") or "") for row in checkpoints[: selected_index + 1]}

        def apply_restore_state(item):
            item["last_restored_checkpoint_id"] = checkpoint_id
            item["task_checkpoints"] = list(item.get("task_checkpoints") or [])[: selected_index + 1]
            item["last_task_checkpoint_id"] = checkpoint_id
            item["_fresh_agent_session_once"] = True
            item["updated_at"] = runtime.utc_now()
            increment_recovery_counter(item, "checkpoint_restores")
            increment_recovery_counter(item, "session_restarts")
            for task in item.get("tasks") or []:
                task_id = str(task.get("id") or "")
                if task_id in accepted_ids:
                    task["status"] = "passed"
                else:
                    task.update({"status": "pending", "checkpoint_id": None, "updated_at": runtime.utc_now()})
            # A restored filesystem invalidates all later validation evidence.
            item["validation_results"] = []
            item.setdefault("manual_actions", []).append({
                "action": "rollback_task",
                "checkpoint_id": checkpoint_id,
                "task_id": selected.get("task_id"),
                "at": runtime.utc_now(),
                "reason": body.reason,
            })

        await runtime.update_run(run_id, apply_restore_state)
        await runtime.record_step_event(run_id, "run", "checkpoint_restored", body.reason or f"Restored {checkpoint_id}.", result)
        return {**result, "run": await get_run(run_id)}
    if action == "approve":
        def approve(item):
            item["approval_state"] = "approved"
            item["approval_decided_at"] = runtime.utc_now()
            item["approval_reason"] = body.reason
            increment_recovery_counter(item, "manual_actions")
        await runtime.update_run(run_id, approve)
        await runtime.record_step_event(run_id, body.step_key or "run", "approved", body.reason or "User approved the current milestone.")
        return await get_run(run_id)
    if action == "reject":
        await runtime.update_run(run_id, lambda item: item.update({"approval_state": "rejected", "approval_decided_at": runtime.utc_now(), "approval_reason": body.reason}))
        return await terminate_run(run_id)
    raise HTTPException(status_code=400, detail=f"Unknown run action: {body.action}")


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


async def rerun_step(run_id: str, body: runtime.RerunStepRequest | None = None) -> dict:
    body = body or runtime.RerunStepRequest()
    run = await get_run(run_id)
    step_key = body.step_key
    mode = (body.mode or "from_step").strip().lower()
    if mode == "validation_only":
        validation_keys = [
            step.get("key")
            for step in run.get("steps", [])
            if any(token in str(step.get("key") or "").lower() for token in ["validation", "run_test", "test", "gate"])
        ]
        step_key = step_key or (validation_keys[0] if validation_keys else None)
    if not step_key:
        failed = next((step.get("key") for step in run.get("steps", []) if step.get("status") in {"failed", "waiting_input"}), None)
        step_key = failed or (run.get("steps") or [{}])[0].get("key")
    if not step_key:
        raise HTTPException(status_code=400, detail="Run has no step to rerun.")
    await runtime.record_step_event(
        run_id,
        step_key,
        "manual_rerun",
        body.reason or f"Manual re-run requested ({mode}).",
        {"mode": mode, "target_step": step_key},
    )
    return await retry_run(run_id, runtime.RetryRunRequest(step_key=step_key))


async def get_run_diff(run_id: str) -> dict:
    run = await get_run(run_id)
    return build_run_diff(run, Path(run["workspace"]))


async def get_failure_classification(run_id: str) -> dict:
    run = await get_run(run_id)
    return classify_run_failures(run)


async def get_steps(run_id: str) -> list[dict]:
    run = await get_run(run_id)
    return await _STEP_STORE.list_for_run(run["id"])


async def get_artifacts(run_id: str, view: str = "supporting") -> list[dict]:
    run = await get_run(run_id)
    artifacts = await _ARTIFACT_STORE.list_for_run(run["id"])
    return filter_artifacts(artifacts, view)


async def get_run_overview(run_id: str) -> dict:
    return build_run_overview(await get_run(run_id))


async def get_run_diagnostics(run_id: str) -> dict:
    run = await get_run(run_id)
    artifacts = filter_artifacts(await _ARTIFACT_STORE.list_for_run(run_id), "all")
    diagnostic = [item for item in artifacts if item.get("visibility") == "diagnostic"]
    return {
        "schema": "aiwf.run-diagnostics.v1",
        "run_id": run_id,
        "status": run.get("status"),
        "available": {
            "console": True,
            "diff": True,
            "patch": True,
            "repair_policy": bool(run.get("error") or any(step.get("error") for step in run.get("steps") or [])),
            "debug_bundle": True,
            "artifact_files": bool(diagnostic),
        },
        "diagnostic_artifact_count": len(diagnostic),
        "diagnostic_artifacts": diagnostic[:100],
        "endpoints": {
            "console": f"/api/workflow-runs/{run_id}/console",
            "diff": f"/api/workflow-runs/{run_id}/diff",
            "patch": f"/api/workflow-runs/{run_id}/patch",
            "repair_policy": f"/api/workflow-runs/{run_id}/repair-policy",
            "debug_bundle": f"/api/workflow-runs/{run_id}/debug-bundle",
            "artifacts": f"/api/workflow-runs/{run_id}/artifacts?view=all",
        },
    }


async def compact_run_artifacts_service(run_id: str) -> dict:
    run = await _assert_not_active(run_id)
    result = compact_run_diagnostics(run, force=True)
    await runtime.refresh_artifacts(run_id)
    return result


async def cancel_run(run_id: str) -> dict:
    return await terminate_run(run_id)


async def list_active_runs() -> dict:
    _cleanup_done_tasks()
    data = await store_repository.read()
    for run in list(data.get("runs", [])):
        project_path = run.get("original_project_path") or run.get("project_path")
        if run.get("status") in ACTIVE_RUN_STATUSES and project_path:
            await _recover_stale_project_active_runs(str(project_path))
    data = await store_repository.read()
    runs = await _RUN_STORE.list_active(ACTIVE_RUN_STATUSES)
    return {"schema": "aiwf.active-runs.v1", "active": runs, "count": len(runs)}


async def list_run_queue() -> dict:
    _cleanup_done_tasks()
    data = await store_repository.read()
    for run in list(data.get("runs", [])):
        project_path = run.get("original_project_path") or run.get("project_path")
        if run.get("status") in ACTIVE_RUN_STATUSES and project_path:
            await _recover_stale_project_active_runs(str(project_path))
    data = await store_repository.read()
    queued = await _RUN_STORE.list_by_status({"queued"})
    active = await _RUN_STORE.list_by_status({"running", "waiting_input", "cancelling"})
    return {"schema": "aiwf.run-queue.v1", "queued": queued, "active": active, "queued_count": len(queued), "active_count": len(active)}


async def get_run_console(run_id: str) -> dict:
    return build_run_console(await get_run(run_id))


async def get_run_version_metadata(run_id: str) -> dict:
    return build_version_metadata(await get_run(run_id))


async def get_patch_preview(run_id: str) -> dict:
    return patch_preview(await get_run(run_id))


async def apply_run_patch(run_id: str, body: runtime.PatchApplyRequest | None = None) -> dict:
    run = await _assert_not_active(run_id)
    approval_mode = str(run.get("approval_mode") or "fully_automatic")
    approval_state = str(run.get("approval_state") or "not_required")
    risk = run.get("risk_assessment") or {}
    requires_approval = (
        approval_mode in {"review_before_apply", "plan_and_patch_only"}
        or (approval_mode == "milestones" and bool(risk.get("high_risk")))
    )
    if requires_approval and approval_state != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "APPROVAL_REQUIRED",
                "message": "Review and approve this patch before applying it to the project.",
                "approval_mode": approval_mode,
            },
        )
    result = apply_patch(run, (body.files if body else None))
    def mark(item):
        item["patch_status"] = "applied"
        item["patch_applied_at"] = result.get("applied_at")
        item["updated_at"] = runtime.utc_now()
    await runtime.update_run(run_id, mark)
    latest = await get_run(run_id)
    runtime.write_text(Path(latest["workspace"]) / ".workflow" / "patch-apply-result.json", json.dumps(result, indent=2, ensure_ascii=False))
    await runtime.refresh_artifacts(run_id)
    return result


async def get_run_artifact_index(run_id: str) -> dict:
    return read_run_artifact_index(await get_run(run_id))


async def get_run_consistency(run_id: str) -> dict:
    run = await get_run(run_id)
    return check_run_consistency(run)


async def repair_run_artifacts_service(run_id: str) -> dict:
    run = await get_run(run_id)
    result = repair_run_artifacts(run)
    await runtime.refresh_artifacts(run_id)
    return result

async def get_run_repair_policy(run_id: str) -> dict:
    run = await get_run(run_id)
    failures = classify_run_failures(run)
    policies = []
    for item in failures.get("step_failures") or []:
        policies.append(policy_for_failure(item.get("error"), step_key=item.get("step_key"), error_code=(item.get("failure") or {}).get("code"), retry_count=0))
    if run.get("error"):
        policies.insert(0, policy_for_failure(run.get("error"), error_code=run.get("error_code"), retry_count=0))
    return {"schema": "aiwf.run-repair-policy.v1", "run_id": run.get("id"), "policies": policies, "failure_count": len(policies)}


async def get_workflow_benchmark() -> dict:
    data = await store_repository.read()
    return summarize_runs(data.get("runs", []))


async def get_run_lifecycle(run_id: str) -> dict:
    run = await get_run(run_id)
    project_path = run.get("original_project_path") or run.get("project_path")
    active_task = runtime.running_tasks.get(run_id)
    proc = runtime.running_processes.get(run_id)
    lock = read_project_lock(project_path) if project_path else None
    return {
        "schema": "aiwf.run-lifecycle.v1",
        "run_id": run_id,
        "status": run.get("status"),
        "project_path": project_path,
        "lock": lock,
        "cancel_requested": bool(run.get("cancel_requested") or run.get("status") == "cancelling"),
        "cancel_reason": run.get("cancel_reason"),
        "run_timeout_sec": run.get("run_timeout_sec"),
        "restart_recoverable": bool(run.get("restart_recoverable")),
        "task_active": bool(active_task and not active_task.done()),
        "process_active": bool(proc and proc.returncode is None),
    }
