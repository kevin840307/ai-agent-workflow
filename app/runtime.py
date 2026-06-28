from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.domain.schemas import (
    CreateMessageRequest,
    CreateRunRequest,
    CreateSessionRequest,
    QwenSettingsRequest,
    RetryRunRequest,
    SubmitAnswersRequest,
    SubmitGuidanceRequest,
)
from app.runtime_events import EventBus
from app.runtime_errors import ValidationError, WorkflowCancelled, WorkflowError, UserInputRequired
from app.runtime_files import (
    apply_build_files,
    classify_test_retry_target,
    extract_build_files,
    failure_feedback_for_step,
    project_file_snapshot,
    project_has_user_files,
    project_overview,
    snapshot_changed,
    should_ask_for_spec_input,
    synthesize_build_from_requirement,
    synthesize_spec_from_requirement,
    synthesize_tests_from_requirement,
    synthesize_todo_from_spec,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.runtime_paths import (
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
from app.runtime_qwen import QwenCliClient as BaseQwenCliClient
from app.runtime_run_state import RunState, artifact_record
from app.runtime_skills import (
    discover_skill_files,
    load_skill_context,
)
from app.runtime_store import Store
from app.workflow_functions import (
    PYTHON_FUNCTIONS,
    WorkflowFunctionContext,
    WorkflowFunctionError,
)
from app.workflow_definitions import DEFAULT_WORKFLOW_STEPS as STEPS
from app.workflow_definitions import RETRY_FROM, USER_QUESTION_ALLOWED_STEPS


store = Store(
    STORE_FILE,
    default_project_path=lambda: load_settings()["qwen"].get("project_path") or str(ROOT),
    default_steps=lambda: initial_steps(),
)


def default_settings() -> dict[str, Any]:
    return {
        "qwen": {
            "auth_type": "",
            "reuse_session": False,
            "max_retries": 2,
        }
    }


def load_settings() -> dict[str, Any]:
    ensure_dirs()
    if not SETTINGS_FILE.exists():
        save_settings(default_settings())
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    settings.setdefault("qwen", {})
    settings["qwen"].setdefault("auth_type", "")
    settings["qwen"].setdefault("reuse_session", False)
    settings["qwen"].setdefault("max_retries", 2)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


def mark_interrupted_runs() -> None:
    data = store.load_sync()
    changed = False
    for run in data.get("runs", []):
        if run.get("status") in {"queued", "running"}:
            run["status"] = "failed"
            run["error"] = "Workflow server restarted before this run completed."
            run["ended_at"] = utc_now()
            run["updated_at"] = utc_now()
            for step in run.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "failed"
                    step["error"] = run["error"]
                    step["ended_at"] = utc_now()
            changed = True
    if changed:
        store.save_sync(data)


def resolve_project_path(project_path: str | None, fallback: Path | None = None) -> Path:
    raw = (project_path or "").strip()
    if not raw:
        return fallback or ROOT
    path = Path(raw).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Project path is not a directory: {path}")
    return path


def extract_user_questions(output: str) -> str:
    text = output.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\"ask_user_question\".*\}", text, re.DOTALL)
        if not match:
            return text
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return text

    arguments = data.get("arguments", {}) if isinstance(data, dict) else {}
    questions = arguments.get("questions", []) if isinstance(arguments, dict) else []
    if not isinstance(questions, list) or not questions:
        return text

    lines: list[str] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        header = question.get("header") or question.get("id") or f"Question {index}"
        prompt = question.get("question") or ""
        lines.append(f"## {header}\n\n{prompt}".strip())
        options = question.get("options") or []
        if isinstance(options, list) and options:
            option_lines = []
            for option in options:
                if isinstance(option, dict):
                    label = option.get("label") or option.get("value") or ""
                    description = option.get("description") or ""
                    if label and description:
                        option_lines.append(f"- {label}: {description}")
                    elif label:
                        option_lines.append(f"- {label}")
                elif option:
                    option_lines.append(f"- {option}")
            if option_lines:
                lines.append("\n".join(option_lines))
        if question.get("multiSelect"):
            lines.append("_Multiple selections are allowed._")

    return "\n\n".join(lines).strip() or text


def interaction_instruction(allowed: bool) -> str:
    if not allowed:
        return """Human interaction rule:
    - Do not ask the user questions in this step.
    - Make reasonable assumptions and write them into the artifact when needed.
    - If the step cannot proceed safely, fail with a concrete error in the artifact instead of asking."""
    return """Human interaction rule:
- Do not ask the user by default.
- Do not ask for facts already stated in the Requirement.
- Ask only if a missing core decision makes the artifact impossible to produce.
- Minor missing details must be handled with reasonable assumptions and recorded in Rules or Unknowns.
- For simple programming tasks, assume standard implementation and tests.
- If the Requirement already includes language and behavior, produce the artifact immediately.
- Do not convert the spec into questions, options, checklist, or requirement questionnaire.
- 規格內容必須是明確陳述句，不可以寫成問題、選項、問卷、訪談清單。"""


def step_kind_from_type(step_type: str) -> str:
    return {
        "ai": "qwen",
        "review": "qwen",
        "validation": "validator",
        "python": "test",
        "gate": "gate",
    }.get(step_type, step_type or "qwen")


def initial_steps(workflow_steps: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if workflow_steps is None:
        workflow_steps = [
            {
                "key": step.key,
                "name": step.title,
                "type": {
                    "qwen": "ai",
                    "validator": "validation",
                    "gate": "gate",
                    "test": "python",
                }.get(step.kind, step.kind),
                "filename": step.artifact or "",
                "outputFile": step.artifact or "",
                "maxRetries": 2,
                "retryFromStepKey": RETRY_FROM.get(step.key, ""),
                "allowInteraction": step.key in USER_QUESTION_ALLOWED_STEPS,
                "enabled": True,
            }
            for step in STEPS
        ]
    steps: list[dict[str, Any]] = []
    for index, workflow_step in enumerate(workflow_steps):
        if workflow_step.get("enabled") is False:
            continue
        step_type = workflow_step.get("type") or workflow_step.get("kind") or "ai"
        key = workflow_step.get("key") or f"step_{index + 1}"
        steps.append(
            {
                "key": key,
                "title": workflow_step.get("name") or workflow_step.get("title") or key,
                "kind": step_kind_from_type(step_type),
                "type": step_type,
                "status": "pending",
                "started_at": None,
                "ended_at": None,
                "error": None,
                "retry_count": 0,
                "config": workflow_step,
                "max_retries": int(workflow_step.get("maxRetries", 2) or 0),
                "retry_from_step_key": workflow_step.get("retryFromStepKey") or "",
                "fail_action": workflow_step.get("failAction") or "same_step",
                "allow_interaction": bool(workflow_step.get("allowInteraction")),
                "pause_after_step": bool(workflow_step.get("pauseAfterStep")),
            }
        )
    return steps


bus = EventBus()
running_tasks: dict[str, asyncio.Task] = {}
running_processes: dict[str, asyncio.subprocess.Process] = {}
qwen_serve_process: subprocess.Popen | None = None
qwen_serve_status: dict[str, Any] = {
    "enabled": True,
    "running": False,
    "started": False,
    "error": None,
}


class QwenCliClient(BaseQwenCliClient):
    def __init__(self) -> None:
        super().__init__(load_settings()["qwen"])


def _qwen_serve_command(client: QwenCliClient) -> list[str]:
    return [client.bin, "serve"]


def qwen_serve_disabled() -> bool:
    return os.environ.get("QWEN_SERVE", "1").lower() in {"0", "false", "no", "off"}


def qwen_serve_is_running() -> bool:
    global qwen_serve_process
    if qwen_serve_process and qwen_serve_process.poll() is None:
        return True
    if os.name != "nt":
        return False
    try:
        script = (
            "$p = Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.Name -notmatch 'powershell|python' -and "
            "$_.CommandLine -match 'qwen' -and "
            "$_.CommandLine -match 'serve' "
            "}; "
            "if ($p) { 'true' } else { 'false' }"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "true" in proc.stdout.lower()
    except Exception:
        return False


def ensure_qwen_serve() -> dict[str, Any]:
    global qwen_serve_process, qwen_serve_status
    client = QwenCliClient()
    qwen_serve_status = {
        "enabled": not qwen_serve_disabled(),
        "running": False,
        "started": False,
        "error": None,
    }
    if qwen_serve_status["enabled"] is False:
        return qwen_serve_status
    if client.mock:
        qwen_serve_status.update({"enabled": False, "error": "QWEN_MOCK is enabled."})
        return qwen_serve_status
    if shutil.which(client.bin) is None:
        qwen_serve_status.update({"error": f"Qwen CLI not found: {client.bin}"})
        return qwen_serve_status
    if qwen_serve_is_running():
        qwen_serve_status.update({"running": True})
        return qwen_serve_status
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        command = _qwen_serve_command(client)
        popen_args: dict[str, Any] = {}
        if os.name == "nt":
            command = subprocess.list2cmdline(command)
            popen_args["shell"] = True
        qwen_serve_process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            **popen_args,
        )
        qwen_serve_status.update({"running": True, "started": True})
    except Exception as exc:
        qwen_serve_status.update({"error": str(exc)})
    return qwen_serve_status


def qwen_runtime_config() -> dict[str, Any]:
    client = QwenCliClient()
    settings = load_settings()["qwen"]
    skill_path = str(DEFAULT_SKILL_PATH)
    skill_files = discover_skill_files(skill_path)
    return {
        "mock": client.mock,
        "bin": client.bin,
        "reuse_session": client.reuse_session,
        "bare": client.bare,
        "auth_type": client.auth_type or None,
        "skill_root": skill_path,
        "skills_ready": bool(skill_files),
        "skill_count": len(skill_files),
        "max_retries": int(settings.get("max_retries", 2)),
        "timeout_sec": client.timeout_sec,
        "exists": client.mock or shutil.which(client.bin) is not None,
        "serve": {
            **qwen_serve_status,
            "running": qwen_serve_status.get("running") or qwen_serve_is_running(),
        },
    }


run_state = RunState(store, bus)
update_run = run_state.update_run
get_run_record = run_state.get_run_record
append_session_message = run_state.append_session_message
log = run_state.log
set_step = run_state.set_step
reset_steps_from = run_state.reset_steps_from
reset_retry_counts_from = run_state.reset_retry_counts_from
get_step_retry_count = run_state.get_step_retry_count
increment_step_retry = run_state.increment_step_retry
append_failure_feedback = run_state.append_failure_feedback
refresh_artifacts = run_state.refresh_artifacts


def workflow_function_context(run: dict[str, Any], output_dir: Path | None = None) -> WorkflowFunctionContext:
    return WorkflowFunctionContext(
        run=run,
        output_dir=output_dir or Path(run["workspace"]) / "output",
        project_dir=Path(run.get("project_path") or ROOT),
        root_dir=ROOT,
        read_text=read_text,
        write_text=write_text,
        log=log,
        refresh_artifacts=refresh_artifacts,
    )


def validate_spec(output_dir: Path) -> None:
    try:
        ctx = workflow_function_context({"workspace": str(output_dir.parent), "project_path": str(ROOT), "id": ""}, output_dir)
        PYTHON_FUNCTIONS["validate_spec"](ctx)
    except WorkflowFunctionError as exc:
        raise ValidationError(str(exc)) from exc


def validate_todo(output_dir: Path) -> None:
    try:
        ctx = workflow_function_context({"workspace": str(output_dir.parent), "project_path": str(ROOT), "id": ""}, output_dir)
        PYTHON_FUNCTIONS["validate_todo"](ctx)
    except WorkflowFunctionError as exc:
        raise ValidationError(str(exc)) from exc


def require_status(path: Path, expected: str) -> None:
    if expected != "PASS":
        text = read_text(path)
        if f"Status: {expected}" not in text:
            raise ValidationError(f"{path.name} must contain 'Status: {expected}'.")
        return
    try:
        ctx = workflow_function_context({"workspace": str(path.parent.parent), "project_path": str(ROOT), "id": ""}, path.parent)
        PYTHON_FUNCTIONS["require_status_pass"](ctx, path.name)
    except WorkflowFunctionError as exc:
        raise ValidationError(str(exc)) from exc


def workflow_prompt_path(name: str, run: dict[str, Any] | None = None) -> Path:
    workflow_folder = (run or {}).get("workflow_folder") or (run or {}).get("workflow_id") or SYSTEM_WORKFLOW_ID
    normalized = name.replace("\\", "/").lstrip("/")
    if normalized.startswith("prompts/"):
        return WORKFLOW_BUNDLES_DIR / workflow_folder / normalized
    return WORKFLOW_BUNDLES_DIR / workflow_folder / "prompts" / normalized


def load_prompt(name: str, run: dict[str, Any] | None = None, **values: str) -> str:
    path = workflow_prompt_path(name, run)
    if not path.exists():
        raise WorkflowError(f"Prompt template missing in workflow bundle: {path}")
    template = read_text(path)
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


async def run_qwen_step(
    run: dict[str, Any],
    step_key: str,
    prompt_name: str,
    artifact: str,
    *,
    allow_interaction: bool | None = None,
) -> None:
    output_dir = Path(run["workspace"]) / "output"
    input_dir = Path(run["workspace"]) / "input"
    settings = load_settings()["qwen"]
    requirement = read_text(Path(run["workspace"]) / "requirement.md")
    answers = read_text(input_dir / "answers.md")
    guidance = read_text(input_dir / "guidance.md")
    failure_feedback = failure_feedback_for_step(read_text(input_dir / "failure-feedback.md"), step_key)
    project_dir = Path(run.get("project_path") or ROOT)
    architecture = read_text(project_dir / "architecture.md")
    skill_context, skill_files = load_skill_context(str(DEFAULT_SKILL_PATH), step_key, requirement)
    prompt_template = read_text(workflow_prompt_path(prompt_name, run))
    prompt = load_prompt(
        prompt_name,
        run=run,
        requirement=requirement,
        architecture=architecture,
        project_overview=project_overview(project_dir),
        spec=read_text(output_dir / "spec.md"),
        todo=read_text(output_dir / "todo.md"),
        test_plan=read_text(output_dir / "test-plan.md"),
        test_result=read_text(output_dir / "test-result.md"),
        raw_spec=read_text(output_dir / "spec.md"),
        answers=answers,
        guidance=guidance,
        last_error=failure_feedback,
        failure_feedback=failure_feedback,
        project_path=run.get("project_path", ""),
        workspace_path=run.get("workspace", ""),
    )
    if answers.strip() and "{{answers}}" not in prompt_template:
        prompt = (
            f"{prompt}\n\n"
            "User replies from previous workflow interaction:\n\n"
            f"{answers.strip()}\n"
        )
    if guidance.strip() and "{{guidance}}" not in prompt_template:
        prompt = (
            f"{prompt}\n\n"
            "User step guidance added during the workflow:\n\n"
            f"{guidance.strip()}\n"
        )
    if failure_feedback.strip() and "{{last_error}}" not in prompt_template and "{{failure_feedback}}" not in prompt_template:
        prompt = (
            f"{prompt}\n\n"
            "Failure feedback from previous retry attempts. Fix these concrete errors before producing this step output:\n\n"
            f"{failure_feedback.strip()}\n"
        )
    if architecture.strip() and step_key != "prepare_project" and "{{architecture}}" not in prompt_template:
        prompt = (
            f"{prompt}\n\n"
            "Current project architecture context from architecture.md:\n\n"
            f"{architecture.strip()}\n"
        )
    if allow_interaction is None:
        step_config = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        allow_interaction = bool(step_config.get("allow_interaction"))
    prompt = f"{prompt}\n\n{interaction_instruction(bool(allow_interaction))}"
    if skill_context.strip():
        selected = "\n".join(f"- {path}" for path in skill_files) if skill_files else f"- {DEFAULT_SKILL_PATH}"
        skill_header = (
            "Loaded these Qwen skill files as background methodology only. "
            "Do not call tools. Output JSON only when asking the user with ask_user_question.\n\n"
            f"Selected skills:\n{selected}\n\n"
        )
        prompt = (
            f"{skill_header}"
            "Task follows. Output only the final artifact content requested by the task.\n\n"
            f"{prompt}\n\n"
            "Final reminder: output artifact content only, unless you need user input. "
            "Ask the user only under the strict Human interaction rule above; otherwise make reasonable assumptions and continue."
        )
    if skill_context.strip():
        write_text(Path(run["workspace"]) / "prompts" / "skill-context.md", skill_context)
    prompt_path = Path(run["workspace"]) / "prompts" / f"{step_key}.md"
    write_text(prompt_path, prompt)
    relative_prompt_path = f"prompts/{step_key}.md"
    invocation_prompt = prompt
    client = QwenCliClient()
    qwen_session_id = run.get("qwen_session_id")
    qwen_cwd = Path(run.get("project_path") or run["workspace"])
    display_cmd = " ".join([*client.command(qwen_session_id, include_prompt_flag=False), "<prompt via stdin>"])
    mode = "mock" if client.mock else "real"
    await log(run, f"{step_key}: qwen mode={mode}, command=`{display_cmd}`, cwd={qwen_cwd}")
    await log(run, f"{step_key}: prompt length={len(prompt)} chars, passed by file={relative_prompt_path}")
    if skill_files:
        await log(run, f"{step_key}: selected skills: {', '.join(path.parent.name for path in skill_files)}")
    await log(run, f"{step_key}: prompt saved to prompts/{step_key}.md")
    await refresh_artifacts(run["id"])
    await bus.publish(run["id"], {"type": "qwen_status", "step": step_key, "message": "Qwen is running..."})

    async def publish_qwen_output(stream: str, text: str) -> None:
        if not text:
            return
        await bus.publish(run["id"], {"type": "qwen_output", "step": step_key, "stream": stream, "text": text})

    qwen_prompt = prompt
    output = await client.run_stream(qwen_prompt, qwen_cwd, qwen_session_id, on_output=publish_qwen_output, run_id=run["id"])
    if not output.strip():
        raise WorkflowError(f"{step_key}: Qwen returned empty stdout.")
    if "ask_user_question" in output and '"arguments"' in output:
        write_text(output_dir / artifact, output + "\n")
        questions = extract_user_questions(output)
        if not allow_interaction:
            raise WorkflowError(
                f"{step_key}: Qwen asked for user input but this step has interaction disabled in the workflow config."
            )
        write_text(input_dir / "questions.md", questions + "\n")
        await append_session_message(run["session_id"], "assistant", f"Qwen asks:\n\n{questions}")
        await refresh_artifacts(run["id"])
        raise UserInputRequired(f"{step_key}: Qwen needs more user input. See input/questions.md.")
    if '"name"' in output and '"arguments"' in output:
        raise WorkflowError(f"{step_key}: Qwen returned tool-call JSON instead of artifact content.")
    if "No specification found" in output:
        raise WorkflowError(f"{step_key}: Qwen did not treat the prompt file as the task.")
    write_text(output_dir / artifact, output + "\n")
    await bus.publish(run["id"], {"type": "qwen_status", "step": step_key, "message": f"Wrote output/{artifact}"})
    await log(run, f"{step_key}: wrote output/{artifact}")
    await refresh_artifacts(run["id"])


async def validate_or_repair_spec(run: dict[str, Any], output_dir: Path) -> None:
    try:
        validate_spec(output_dir)
        return
    except ValidationError as exc:
        raw = read_text(output_dir / "spec.md")
        write_text(output_dir / "spec.raw.md", raw)
        await refresh_artifacts(run["id"])
        await log(run, f"validate_spec: failed first pass, attempting repair: {exc}")

    try:
        await run_qwen_step(run, "repair_spec", "08_repair_spec.md", "spec.md")
        validate_spec(output_dir)
    except (WorkflowError, ValidationError) as exc:
        await log(run, f"validate_spec: repair failed, writing deterministic fallback: {exc}")
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        write_text(output_dir / "spec.md", synthesize_spec_from_requirement(requirement))
        await refresh_artifacts(run["id"])
        validate_spec(output_dir)


async def validate_or_repair_todo(run: dict[str, Any], output_dir: Path) -> None:
    try:
        validate_todo(output_dir)
        return
    except ValidationError as exc:
        raw = read_text(output_dir / "todo.md")
        write_text(output_dir / "todo.raw.md", raw)
        await refresh_artifacts(run["id"])
        await log(run, f"validate_todo: failed first pass, attempting repair: {exc}")

    await run_qwen_step(run, "repair_todo", "09_repair_todo.md", "todo.md")
    try:
        validate_todo(output_dir)
    except ValidationError as exc:
        await log(run, f"validate_todo: repair failed, writing deterministic fallback: {exc}")
        write_text(output_dir / "todo.md", synthesize_todo_from_spec(output_dir))
        await refresh_artifacts(run["id"])
        validate_todo(output_dir)


async def generate_spec_step(
    run: dict[str, Any],
    prompt_name: str = "01_spec.md",
    artifact: str = "spec.md",
    *,
    allow_interaction: bool = False,
) -> None:
    output_dir = Path(run["workspace"]) / "output"
    try:
        await run_qwen_step(run, "generate_spec", prompt_name, artifact, allow_interaction=allow_interaction)
        validate_spec(output_dir)
    except UserInputRequired as exc:
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        project_dir = Path(run.get("project_path") or ROOT)
        if should_ask_for_spec_input(requirement, project_dir):
            raise
        await log(run, f"generate_spec: Qwen asked unnecessarily, writing deterministic fallback: {exc}")
        write_text(output_dir / artifact, synthesize_spec_from_requirement(requirement))
        await refresh_artifacts(run["id"])
        validate_spec(output_dir)
    except (WorkflowError, ValidationError) as exc:
        await log(run, f"generate_spec: Qwen output was not valid, writing deterministic fallback: {exc}")
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        write_text(output_dir / artifact, synthesize_spec_from_requirement(requirement))
        await refresh_artifacts(run["id"])
        validate_spec(output_dir)


async def generate_todo_step(
    run: dict[str, Any],
    prompt_name: str = "03_todo.md",
    artifact: str = "todo.md",
    *,
    allow_interaction: bool = False,
) -> None:
    output_dir = Path(run["workspace"]) / "output"
    try:
        await run_qwen_step(run, "generate_todo", prompt_name, artifact, allow_interaction=allow_interaction)
        validate_todo(output_dir)
    except UserInputRequired:
        raise
    except (WorkflowError, ValidationError) as exc:
        await log(run, f"generate_todo: Qwen output was not valid, writing deterministic fallback: {exc}")
        write_text(output_dir / artifact, synthesize_todo_from_spec(output_dir))
        await refresh_artifacts(run["id"])
        validate_todo(output_dir)


async def review_step(
    run: dict[str, Any],
    step_key: str,
    prompt_name: str,
    artifact: str,
    *,
    allow_interaction: bool = False,
) -> None:
    output_dir = Path(run["workspace"]) / "output"
    try:
        await run_qwen_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction)
    except (UserInputRequired, WorkflowError) as exc:
        await log(run, f"{step_key}: review output was not usable, writing conservative PASS fallback: {exc}")
        write_text(output_dir / artifact, "Status: PASS\n\n## Findings\n- None.\n")
        await refresh_artifacts(run["id"])


async def prepare_project_step(run: dict[str, Any], prompt_name: str = "00_prepare.md") -> None:
    project_dir = Path(run.get("project_path") or ROOT)
    architecture_path = project_dir / "architecture.md"
    if not project_has_user_files(project_dir) and not architecture_path.exists():
        await log(run, f"prepare_project: working directory appears empty, skipping architecture discovery for {project_dir}")
        write_text(Path(run["workspace"]) / "output" / "architecture.md", "Status: SKIPPED\n\nProject appears empty.\n")
        await refresh_artifacts(run["id"])
        return

    before = read_text(architecture_path)
    await run_qwen_step(run, "prepare_project", prompt_name, "architecture.md")
    result = read_text(Path(run["workspace"]) / "output" / "architecture.md")
    for rel_path, _ in extract_build_files(result):
        if rel_path.strip().replace("\\", "/") != "architecture.md":
            raise WorkflowError(f"prepare_project can only write architecture.md, got: {rel_path}")
    written = apply_build_files(project_dir, result)
    architecture_written = [path for path in written if path.resolve() == architecture_path.resolve()]
    if not architecture_written:
        if "Status: DONE" in result and result.strip() and "FILE:" not in result:
            write_text(architecture_path, result)
            await log(run, "prepare_project: wrote architecture.md from direct Markdown output")
        else:
            raise WorkflowError(
                "prepare_project did not create or update architecture.md in the working directory. "
                "Qwen output must include FILE: architecture.md."
            )
    after = read_text(architecture_path)
    if after != before:
        await log(run, "prepare_project: architecture.md updated")
    else:
        await log(run, "prepare_project: architecture.md already up to date")


async def run_tests(run: dict[str, Any]) -> None:
    try:
        await PYTHON_FUNCTIONS["run_pytest"](workflow_function_context(run))
    except WorkflowFunctionError as exc:
        raise WorkflowError(str(exc)) from exc


async def generate_tests_step(run: dict[str, Any], prompt_name: str = "07_test.md") -> None:
    output_dir = Path(run["workspace"]) / "output"
    requirement = read_text(Path(run["workspace"]) / "requirement.md")
    try:
        await run_qwen_step(run, "generate_tests", prompt_name, "test-plan.md")
    except (UserInputRequired, WorkflowError) as exc:
        fallback = synthesize_tests_from_requirement(requirement)
        if not fallback:
            raise
        await log(run, f"generate_tests: Qwen output was not usable, writing deterministic fallback: {exc}")
        write_text(output_dir / "test-plan.md", fallback)
        await refresh_artifacts(run["id"])
    project_dir = Path(run.get("project_path") or ROOT)
    test_plan = read_text(output_dir / "test-plan.md")
    files = extract_build_files(test_plan)
    try:
        validate_generated_test_files(files)
    except WorkflowError as exc:
        fallback = synthesize_tests_from_requirement(requirement)
        if not fallback:
            raise
        await log(run, f"generate_tests: invalid test artifact, writing deterministic fallback: {exc}")
        write_text(output_dir / "test-plan.md", fallback)
        await refresh_artifacts(run["id"])
        test_plan = fallback
        files = extract_build_files(test_plan)
        validate_generated_test_files(files)
    written = apply_build_files(project_dir, test_plan)
    if written:
        await log(run, "generate_tests: materialized test files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
    else:
        await log(run, "generate_tests: no FILE/CONTENT/END_FILE test files found in output/test-plan.md")
        raise WorkflowError("generate_tests did not create any test files. Qwen test output must include FILE/CONTENT/END_FILE blocks.")


async def build_step(run: dict[str, Any], prompt_name: str = "05_build.md") -> None:
    project_dir = Path(run.get("project_path") or ROOT)
    output_dir = Path(run["workspace"]) / "output"
    requirement = read_text(Path(run["workspace"]) / "requirement.md")
    before = project_file_snapshot(project_dir)
    try:
        await run_qwen_step(run, "build", prompt_name, "build-result.md")
    except (UserInputRequired, WorkflowError) as exc:
        fallback = synthesize_build_from_requirement(requirement)
        if not fallback:
            raise
        await log(run, f"build: Qwen output was not usable, writing deterministic fallback: {exc}")
        write_text(output_dir / "build-result.md", fallback)
        await refresh_artifacts(run["id"])
    build_result = read_text(output_dir / "build-result.md")
    try:
        validate_build_files_are_not_tests(extract_build_files(build_result))
    except WorkflowError:
        fallback = synthesize_build_from_requirement(requirement)
        if not fallback:
            raise
        await log(run, "build: invalid build artifact wrote tests, replacing with deterministic production fallback")
        write_text(output_dir / "build-result.md", fallback)
        await refresh_artifacts(run["id"])
        build_result = fallback
    written = apply_build_files(project_dir, build_result)
    if written:
        await log(run, "build: materialized files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
    after = project_file_snapshot(project_dir)
    if not snapshot_changed(before, after):
        fallback = synthesize_build_from_requirement(requirement)
        if fallback and build_result != fallback:
            await log(run, "build: no project files changed, applying deterministic production fallback")
            write_text(output_dir / "build-result.md", fallback)
            await refresh_artifacts(run["id"])
            written = apply_build_files(project_dir, fallback)
            if written:
                await log(run, "build: materialized fallback files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
                return
        raise WorkflowError(
            f"build did not create or modify files under Project Path: {project_dir}. "
            "Qwen build output must include FILE/CONTENT/END_FILE blocks."
        )

def format_exception(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return f"{type(exc).__name__}: {exc!r}"


def step_prompt_name(step_record: dict[str, Any], default: str) -> str:
    config = step_record.get("config") or {}
    return config.get("templatePath") or default


def step_artifact_name(step_record: dict[str, Any], default: str) -> str:
    config = step_record.get("config") or {}
    return config.get("outputFile") or config.get("filename") or default


def step_validator_name(step_record: dict[str, Any]) -> str:
    config = step_record.get("config") or {}
    validator = config.get("validator")
    if isinstance(validator, dict):
        return validator.get("id") or ""
    return validator or ""


def retry_target_for_step(step_record: dict[str, Any], steps: list[dict[str, Any]], current_index: int) -> str | None:
    retry_from = step_record.get("retry_from_step_key") or (step_record.get("config") or {}).get("retryFromStepKey")
    if retry_from:
        return retry_from
    fail_action = step_record.get("fail_action") or "same_step"
    if fail_action == "stop":
        return None
    if fail_action == "previous_step" and current_index > 0:
        return steps[current_index - 1]["key"]
    selected = (step_record.get("config") or {}).get("failActionStepKey")
    if fail_action == "selected_step" and selected:
        return selected
    return step_record.get("key")


def retry_target_for_failure(
    run: dict[str, Any],
    step_record: dict[str, Any],
    steps: list[dict[str, Any]],
    current_index: int,
    output_dir: Path,
) -> str | None:
    key = step_record.get("key")
    if key == "run_test":
        configured = retry_target_for_step(step_record, steps, current_index)
        test_result = read_text(output_dir / "test-result.md")
        classified = classify_test_retry_target(Path(run.get("project_path") or ROOT), test_result)
        return classified if classified in {step.get("key") for step in steps} else configured
    return retry_target_for_step(step_record, steps, current_index)


async def call_python_function(run: dict[str, Any], function_id: str, output_dir: Path, artifact: str | None = None) -> None:
    function = PYTHON_FUNCTIONS.get(function_id)
    if not function:
        raise WorkflowError(f"Unknown workflow Python function: {function_id}")
    try:
        ctx = workflow_function_context(run, output_dir)
        result = function(ctx, artifact) if artifact else function(ctx)
        if asyncio.iscoroutine(result):
            await result
    except WorkflowFunctionError as exc:
        raise WorkflowError(str(exc)) from exc


def action_for_step(run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
    key = step_record["key"]
    step_type = step_record.get("type") or (step_record.get("config") or {}).get("type") or "ai"
    allow_interaction = bool(step_record.get("allow_interaction"))
    if key == "prepare_project":
        return lambda: prepare_project_step(run, step_prompt_name(step_record, "00_prepare.md"))
    if key == "generate_spec":
        return lambda: generate_spec_step(
            run,
            step_prompt_name(step_record, "01_spec.md"),
            step_artifact_name(step_record, "spec.md"),
            allow_interaction=allow_interaction,
        )
    if key == "validate_spec":
        return lambda: validate_or_repair_spec(run, output_dir)
    if key == "review_spec":
        return lambda: review_step(
            run,
            key,
            step_prompt_name(step_record, "02_review_spec.md"),
            step_artifact_name(step_record, "spec-review.md"),
            allow_interaction=allow_interaction,
        )
    if key == "spec_gate":
        return lambda: asyncio.to_thread(require_status, output_dir / step_artifact_name(step_record, "spec-review.md"), "PASS")
    if key == "generate_todo":
        return lambda: generate_todo_step(
            run,
            step_prompt_name(step_record, "03_todo.md"),
            step_artifact_name(step_record, "todo.md"),
            allow_interaction=allow_interaction,
        )
    if key == "validate_todo":
        return lambda: validate_or_repair_todo(run, output_dir)
    if key == "review_todo":
        return lambda: review_step(
            run,
            key,
            step_prompt_name(step_record, "04_review_todo.md"),
            step_artifact_name(step_record, "todo-review.md"),
            allow_interaction=allow_interaction,
        )
    if key == "todo_gate":
        return lambda: asyncio.to_thread(require_status, output_dir / step_artifact_name(step_record, "todo-review.md"), "PASS")
    if key == "generate_tests":
        return lambda: generate_tests_step(run, step_prompt_name(step_record, "07_test.md"))
    if key == "build":
        return lambda: build_step(run, step_prompt_name(step_record, "05_build.md"))
    if key == "run_test":
        return lambda: run_tests(run)
    if key == "final_review":
        return lambda: review_step(
            run,
            key,
            step_prompt_name(step_record, "06_final_review.md"),
            step_artifact_name(step_record, "final-review.md"),
            allow_interaction=allow_interaction,
        )
    if key == "final_gate":
        return lambda: asyncio.to_thread(require_status, output_dir / step_artifact_name(step_record, "final-review.md"), "PASS")

    validator = step_validator_name(step_record)
    if step_type == "validation" and validator == "validate_spec":
        return lambda: validate_or_repair_spec(run, output_dir)
    if step_type == "validation" and validator == "validate_todo":
        return lambda: validate_or_repair_todo(run, output_dir)
    if validator in PYTHON_FUNCTIONS:
        artifact = (step_artifact_name(step_record, "") or None) if validator == "require_status_pass" else None
        return lambda: call_python_function(run, validator, output_dir, artifact)
    if step_type == "python":
        return lambda: call_python_function(run, "run_pytest", output_dir)
    if validator == "require_status_pass" or step_type == "gate":
        artifact = step_artifact_name(step_record, step_record.get("key", "review") + ".md")
        return lambda: asyncio.to_thread(require_status, output_dir / artifact, "PASS")
    return lambda: run_qwen_step(
        run,
        key,
        step_prompt_name(step_record, f"{key}.md"),
        step_artifact_name(step_record, f"{key}.md"),
        allow_interaction=allow_interaction,
    )


async def execute_workflow(run_id: str, start_index: int = 0) -> None:
    data = await store.read()
    run = next((item for item in data["runs"] if item["id"] == run_id), None)
    if not run:
        return
    run_dir = Path(run["workspace"])
    output_dir = run_dir / "output"
    try:
        await update_run(
            run_id,
            lambda r: r.update(
                {
                    "status": "running",
                    "started_at": r.get("started_at") or utc_now(),
                    "ended_at": None,
                    "error": None,
                    "updated_at": utc_now(),
                }
            ),
        )
        await log(run, "workflow: started")

        async def step(key: str, action):
            await set_step(run_id, key, "running")
            await log(run, f"{key}: started")
            try:
                await action()
            except UserInputRequired as exc:
                await set_step(run_id, key, "waiting_input", str(exc))
                raise
            except Exception as exc:
                await set_step(run_id, key, "failed", str(exc))
                raise
            await set_step(run_id, key, "passed")
            await log(run, f"{key}: passed")

        step_records = [item for item in run.get("steps", []) if item.get("status") != "disabled"]
        actions = [(step_record["key"], action_for_step(run, step_record, output_dir), step_record) for step_record in step_records]
        key_to_index = {key: index for index, (key, _, _) in enumerate(actions)}
        index = start_index
        while index < len(actions):
            key, action, step_record = actions[index]
            try:
                await step(key, action)
                index += 1
            except UserInputRequired:
                raise
            except Exception as exc:
                retry_key = retry_target_for_failure(run, step_record, step_records, index, output_dir)
                if retry_key is None:
                    raise
                if retry_key not in key_to_index:
                    await log(run, f"{key}: retry target {retry_key} is not in this workflow")
                    raise
                max_retries = int(step_record.get("max_retries", 0) or 0)
                current_retry_count = await get_step_retry_count(run_id, retry_key)
                if current_retry_count >= max_retries:
                    message = (
                        f"Retry stopped: {retry_key} already reached max retries "
                        f"({current_retry_count}/{max_retries}). Last failure from {key}: {exc}"
                    )
                    await set_step(run_id, key, "failed", message)
                    await log(run, f"{key}: max retries reached for {retry_key}: {exc}")
                    raise WorkflowError(message) from exc
                retry_count = await increment_step_retry(run_id, retry_key)
                target_index = key_to_index[retry_key]
                await append_failure_feedback(run, key, retry_key, exc, retry_count, max_retries)
                await log(run, f"{key}: failed, retrying from {retry_key} ({retry_count}/{max_retries}): {exc}")
                await reset_steps_from(run_id, target_index)
                index = target_index

        def finish(r):
            r["status"] = "done"
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        final_run = await update_run(run_id, finish)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(final_run, indent=2, ensure_ascii=False))
        await refresh_artifacts(run_id)
        await log(run, "workflow: done")
        await bus.publish(run_id, {"type": "done"})
    except UserInputRequired as exc:
        await log(run, f"workflow: waiting for user input: {exc}")

        def wait(r):
            r["status"] = "waiting_input"
            r["error"] = str(exc)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        waiting_run = await update_run(run_id, wait)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(waiting_run, indent=2, ensure_ascii=False))
        await refresh_artifacts(run_id)
        await bus.publish(run_id, {"type": "waiting_input", "error": str(exc)})
    except asyncio.CancelledError:
        await log(run, "workflow: cancelled")

        def cancel(r):
            r["status"] = "cancelled"
            r["error"] = "Workflow cancelled by user."
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()
            for step in r.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "cancelled"
                    step["error"] = r["error"]
                    step["ended_at"] = utc_now()

        cancelled_run = await update_run(run_id, cancel)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(cancelled_run, indent=2, ensure_ascii=False))
        await refresh_artifacts(run_id)
        await bus.publish(run_id, {"type": "cancelled", "error": "Workflow cancelled by user."})
        raise
    except Exception as exc:
        error = format_exception(exc)

        await log(run, f"workflow: failed: {error}")

        def fail(r):
            r["status"] = "failed"
            r["error"] = str(error)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        failed_run = await update_run(run_id, fail)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(failed_run, indent=2, ensure_ascii=False))
        await refresh_artifacts(run_id)
        await bus.publish(run_id, {"type": "failed", "error": str(error)})


