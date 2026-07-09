from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

# Keep schema imports for backward compatibility with existing route modules that
# import these names from runtime.py.
from app.domain.schemas import (  # noqa: F401
    AgentSettingsRequest,
    CreateMessageRequest,
    CreateRunRequest,
    CreateSessionRequest,
    RetryRunRequest,
    PatchApplyRequest,
    RerunStepRequest,
    SubmitAnswersRequest,
    SubmitGuidanceRequest,
    StepControlRequest,
)
from app.runtime_modules.events import EventBus
from app.runtime_modules.errors import ValidationError, WorkflowCancelled, WorkflowError, UserInputRequired  # noqa: F401
from app.core.paths import (
    DATA_DIR,
    DEFAULT_SKILL_PATH,
    ROOT,
    SETTINGS_FILE,
    STATIC_DIR,
    STORE_FILE,
    SYSTEM_WORKFLOW_ID,
    WORKFLOW_BUNDLES_DIR,
    WORKSPACES_DIR,
    ensure_dirs,
    read_text,
    utc_now,
    write_text,
)
from app.runtime_modules.run_state import RunState, artifact_record  # noqa: F401
from app.runtime_modules.run_owner import current_run_owner, owner_matches_current_process, owner_process_is_alive
from app.persistence.json_store import Store
from app.persistence.sqlite_store import SQLiteStore

from app.workflow_runtime.actions import WorkflowActions
from app.workflow_runtime.agent_step_runner import AgentStepRunner
from app.workflow_runtime.agents import AgentManager, create_agent_manager
from app.workflow_runtime.executor import WorkflowExecutor
from app.workflow_engine.kernel import WorkflowEngineKernel
from app.workflow_runtime.functions import WorkflowFunctionService
from app.workflow_runtime.prompt_builder import PromptBuilder, load_prompt, workflow_prompt_path
from app.workflow_runtime.questions import extract_user_questions, interaction_instruction
from app.workflow_runtime import qwen_serve as _qwen_serve
from app.workflow_runtime.qwen_serve import QwenCliClient
from app.workflow_runtime.retry_policy import retry_target_for_failure, retry_target_for_step
from app.workflow_runtime.settings import default_settings, load_settings, resolve_project_path, save_settings
from app.workflow_runtime.run_lifecycle import clear_project_lock, mark_interrupted_store_runs
from app.workflow_runtime.step_config import initial_steps, step_kind_from_type
from app.workflow_runtime.step_utils import format_exception, step_artifact_name, step_prompt_name, step_function_name


SQLITE_STORE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}


def _resolve_store_backend() -> str:
    """Resolve the persistence backend without surprising existing CLI tests.

    Production/dev runs default to SQLite.  A legacy explicit JSON
    AIWF_STORE_FILE still means file-backed persistence unless the operator also
    sets AIWF_STORE_BACKEND=sqlite.
    """
    configured = os.environ.get("AIWF_STORE_BACKEND")
    if configured:
        backend = configured.strip().lower()
        return "sqlite" if backend in {"sqlite", "sqlite3"} else "file"
    configured_file = os.environ.get("AIWF_STORE_FILE")
    if configured_file:
        suffix = Path(configured_file).suffix.lower()
        return "sqlite" if suffix in SQLITE_STORE_SUFFIXES else "file"
    return "sqlite"


def _store_paths_for_backend(backend: str) -> tuple[Path, Path | None]:
    configured_file = os.environ.get("AIWF_STORE_FILE")
    if backend == "sqlite":
        raw_path = Path(configured_file) if configured_file else DATA_DIR / "store.sqlite3"
        legacy_json_path: Path | None = STORE_FILE if not configured_file else None
        if raw_path.suffix.lower() not in SQLITE_STORE_SUFFIXES:
            if raw_path.suffix.lower() == ".json":
                legacy_json_path = raw_path
            raw_path = raw_path.with_suffix(".sqlite3")
        elif configured_file:
            legacy_candidate = raw_path.with_suffix(".json")
            legacy_json_path = legacy_candidate if legacy_candidate.exists() else None
        return raw_path, legacy_json_path
    return Path(configured_file) if configured_file else STORE_FILE, None


def _has_persisted_state(data: dict[str, Any]) -> bool:
    return any(data.get(key) for key in ("sessions", "messages", "runs", "workflow_configs"))


def _migrate_legacy_json_store(sqlite_store: SQLiteStore, legacy_json_path: Path | None) -> None:
    if legacy_json_path is None or not legacy_json_path.exists():
        return
    if _has_persisted_state(sqlite_store.load_sync()):
        return
    try:
        legacy_data = json.loads(legacy_json_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(legacy_data, dict) and _has_persisted_state(legacy_data):
        sqlite_store.save_sync(legacy_data)


def _create_store_backend():
    backend = _resolve_store_backend()
    path, legacy_json_path = _store_paths_for_backend(backend)
    default_project = lambda: load_settings()["qwen"].get("project_path") or str(ROOT)
    if backend == "sqlite":
        sqlite_store = SQLiteStore(path, default_project_path=default_project, default_steps=lambda: [])
        _migrate_legacy_json_store(sqlite_store, legacy_json_path)
        return sqlite_store
    return Store(path, default_project_path=default_project, default_steps=lambda: [])


def store_backend_name() -> str:
    return "sqlite" if isinstance(store, SQLiteStore) else "file"


def store_path() -> Path:
    return Path(store.path)


store = _create_store_backend()

bus = EventBus()
running_tasks: dict[str, asyncio.Task] = {}
running_processes: dict[str, asyncio.subprocess.Process] = {}

qwen_serve_process = _qwen_serve.qwen_serve_process
qwen_serve_status = _qwen_serve.qwen_serve_status


def qwen_serve_disabled() -> bool:
    return _qwen_serve.qwen_serve_disabled()


def qwen_serve_is_running() -> bool:
    return _qwen_serve.qwen_serve_is_running()


def ensure_qwen_serve() -> dict[str, Any]:
    global qwen_serve_process, qwen_serve_status
    status = _qwen_serve.ensure_qwen_serve()
    qwen_serve_process = _qwen_serve.qwen_serve_process
    qwen_serve_status = _qwen_serve.qwen_serve_status
    return status


def qwen_runtime_config() -> dict[str, Any]:
    global qwen_serve_process, qwen_serve_status
    config = _qwen_serve.qwen_runtime_config()
    qwen_serve_process = _qwen_serve.qwen_serve_process
    qwen_serve_status = _qwen_serve.qwen_serve_status
    # Additive only: existing UI can keep reading old qwen keys, while new UI can
    # discover all available agents from this nested field.
    config["agents"] = agent_manager.health() if "agent_manager" in globals() else {}
    return config

run_state = RunState(store, bus)
update_run = run_state.update_run
get_run_record = run_state.get_run_record
transition_run_status = run_state.transition_run_status
append_session_message = run_state.append_session_message
update_message = run_state.update_message
log = run_state.log
set_step = run_state.set_step
reset_steps_from = run_state.reset_steps_from
reset_retry_counts_from = run_state.reset_retry_counts_from
get_step_retry_count = run_state.get_step_retry_count
increment_step_retry = run_state.increment_step_retry
append_failure_feedback = run_state.append_failure_feedback
refresh_artifacts = run_state.refresh_artifacts
record_step_event = run_state.record_step_event

agent_manager: AgentManager = create_agent_manager()
prompt_builder = PromptBuilder()
function_service = WorkflowFunctionService(log=log, refresh_artifacts=refresh_artifacts)
agent_step_runner = AgentStepRunner(
    agent_manager=agent_manager,
    prompt_builder=prompt_builder,
    bus=bus,
    log=log,
    refresh_artifacts=refresh_artifacts,
    append_session_message=append_session_message,
)
workflow_actions = WorkflowActions(
    agent_runner=agent_step_runner,
    functions=function_service,
    log=log,
    refresh_artifacts=refresh_artifacts,
)
workflow_executor = WorkflowExecutor(
    store=store,
    bus=bus,
    actions=workflow_actions,
    update_run=update_run,
    set_step=set_step,
    reset_steps_from=reset_steps_from,
    get_step_retry_count=get_step_retry_count,
    increment_step_retry=increment_step_retry,
    append_failure_feedback=append_failure_feedback,
    refresh_artifacts=refresh_artifacts,
    log=log,
    record_step_event=record_step_event,
    transition_run_status=transition_run_status,
)
workflow_kernel = WorkflowEngineKernel(executor=workflow_executor, actions=workflow_actions, store=store, bus=bus)


def mark_interrupted_runs() -> None:
    data = store.load_sync()
    changed_runs = mark_interrupted_store_runs(data)
    if not changed_runs:
        return
    store.save_sync(data)
    for run in changed_runs:
        try:
            run_dir = Path(run.get("workspace") or "")
            if run_dir:
                (run_dir / ".workflow").mkdir(parents=True, exist_ok=True)
                write_text(run_dir / ".workflow" / "state.json", json.dumps(run, indent=2, ensure_ascii=False))
                previous = read_text(run_dir / ".workflow" / "run-log.md")
                write_text(
                    run_dir / ".workflow" / "run-log.md",
                    previous + ("\n" if previous.strip() else "") + f"{utc_now()} workflow: interrupted by server restart; run marked failed and retryable.\n",
                )
            clear_project_lock(run)
        except Exception:
            # Startup recovery must never prevent the API from booting.
            continue

def validate_spec(output_dir: Path) -> None:
    return function_service.validate_spec(output_dir)


def validate_todo(output_dir: Path) -> None:
    return function_service.validate_todo(output_dir)


def require_status(path: Path, expected: str) -> None:
    return function_service.require_status(path, expected)


async def call_python_function(run: dict[str, Any], function_id: str, output_dir: Path, artifact: str | None = None) -> None:
    return await function_service.call_python_function(run, function_id, output_dir, artifact)


async def run_agent_step(
    run: dict[str, Any],
    step_key: str,
    prompt_name: str,
    artifact: str,
    *,
    allow_interaction: bool | None = None,
    agent_name: str | None = None,
) -> None:
    return await workflow_actions.run_agent_step(
        run,
        step_key,
        prompt_name,
        artifact,
        allow_interaction=allow_interaction,
        agent_name=agent_name,
    )


async def run_qwen_step(
    run: dict[str, Any],
    step_key: str,
    prompt_name: str,
    artifact: str,
    *,
    allow_interaction: bool | None = None,
) -> None:
    return await workflow_actions.run_qwen_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction)


async def validate_or_repair_spec(run: dict[str, Any], output_dir: Path) -> None:
    return await workflow_actions.validate_or_repair_spec(run, output_dir)


async def validate_or_repair_todo(run: dict[str, Any], output_dir: Path) -> None:
    return await workflow_actions.validate_or_repair_todo(run, output_dir)


async def generate_spec_step(
    run: dict[str, Any],
    prompt_name: str = "01_spec.md",
    artifact: str = "spec.md",
    *,
    allow_interaction: bool = False,
) -> None:
    return await workflow_actions.generate_spec_step(run, prompt_name, artifact, allow_interaction=allow_interaction)


async def generate_todo_step(
    run: dict[str, Any],
    prompt_name: str = "03_todo.md",
    artifact: str = "todo.md",
    *,
    allow_interaction: bool = False,
) -> None:
    return await workflow_actions.generate_todo_step(run, prompt_name, artifact, allow_interaction=allow_interaction)


async def review_step(
    run: dict[str, Any],
    step_key: str,
    prompt_name: str,
    artifact: str,
    *,
    allow_interaction: bool = False,
) -> None:
    return await workflow_actions.review_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction)


async def prepare_project_step(run: dict[str, Any], prompt_name: str = "00_prepare.md") -> None:
    return await workflow_actions.prepare_project_step(run, prompt_name)


async def run_tests(run: dict[str, Any]) -> None:
    return await workflow_actions.run_tests(run)


async def generate_tests_step(run: dict[str, Any], prompt_name: str = "07_test.md") -> None:
    return await workflow_actions.generate_tests_step(run, prompt_name)


async def build_step(run: dict[str, Any], prompt_name: str = "05_build.md") -> None:
    return await workflow_actions.build_step(run, prompt_name)


def action_for_step(run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
    return workflow_actions.action_for_step(run, step_record, output_dir)


async def execute_workflow(run_id: str, start_index: int = 0) -> None:
    return await workflow_kernel.execute(run_id, start_index)
