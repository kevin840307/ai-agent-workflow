from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.mock_qwen import mock_qwen_response
from app.workflow_definitions import DEFAULT_WORKFLOW_STEPS as STEPS
from app.workflow_definitions import RETRY_FROM, SKILLS_BY_STEP, USER_QUESTION_ALLOWED_STEPS


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
WORKSPACES_DIR = ROOT / "workspaces"
STATIC_DIR = ROOT / "static"
PROMPTS_DIR = ROOT / "prompts"
STORE_FILE = DATA_DIR / "store.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_SKILL_PATH = Path.home() / ".qwen" / "skills"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    WORKSPACES_DIR.mkdir(exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class CreateRunRequest(BaseModel):
    requirement: str | None = None
    test_command: str | None = None
    project_path: str | None = None


class CreateSessionRequest(BaseModel):
    project_path: str | None = None
    title: str | None = None


class QwenSettingsRequest(BaseModel):
    auth_type: str | None = None
    reuse_session: bool | None = None
    max_retries: int | None = None


class RetryRunRequest(BaseModel):
    step_key: str | None = None


class SubmitAnswersRequest(BaseModel):
    content: str = Field(min_length=1)
    step_key: str | None = None


class SubmitGuidanceRequest(BaseModel):
    content: str = Field(min_length=1)
    step_key: str


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    def _empty(self) -> dict[str, Any]:
        return {"sessions": [], "messages": [], "runs": []}

    def load_sync(self) -> dict[str, Any]:
        ensure_dirs()
        if not self.path.exists():
            self.save_sync(self._empty())
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        changed = False
        for session in data.get("sessions", []):
            if not session.get("qwen_session_id"):
                session["qwen_session_id"] = session["id"]
                changed = True
            if not session.get("project_path"):
                session["project_path"] = load_settings()["qwen"].get("project_path") or str(ROOT)
                changed = True
        for run in data.get("runs", []):
            if not run.get("qwen_session_id"):
                run["qwen_session_id"] = run["session_id"]
                changed = True
            existing_steps = {step.get("key"): step for step in run.get("steps", [])}
            ordered_steps = []
            for workflow_step in STEPS:
                step = existing_steps.get(workflow_step.key)
                if step is None:
                    step = {
                        "key": workflow_step.key,
                        "title": workflow_step.title,
                        "kind": workflow_step.kind,
                        "status": "pending",
                        "started_at": None,
                        "ended_at": None,
                        "error": None,
                        "retry_count": 0,
                    }
                    changed = True
                else:
                    step["title"] = workflow_step.title
                    step["kind"] = workflow_step.kind
                ordered_steps.append(step)
            if run.get("steps") != ordered_steps:
                run["steps"] = ordered_steps
                changed = True
            for step in run.get("steps", []):
                if "retry_count" not in step:
                    step["retry_count"] = 0
                    changed = True
        if changed:
            self.save_sync(data)
        return data

    def save_sync(self, data: dict[str, Any]) -> None:
        ensure_dirs()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self.path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)

    async def mutate(self, fn):
        async with self._lock:
            data = self.load_sync()
            result = fn(data)
            self.save_sync(data)
            return result

    async def read(self) -> dict[str, Any]:
        async with self._lock:
            return self.load_sync()


store = Store(STORE_FILE)


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


class WorkflowError(Exception):
    pass


class ValidationError(WorkflowError):
    pass


class UserInputRequired(WorkflowError):
    pass


class WorkflowCancelled(WorkflowError):
    pass


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


def interaction_instruction() -> str:
    return """Human interaction rule:
- Ask the user only when progress is genuinely blocked by a missing decision.
- Do not ask for preferences, nice-to-have details, naming, wording, or choices that can be handled with reasonable assumptions.
- If the project is empty and no language/runtime/framework is inferable, ask which language or stack to use.
- If the requested spec is too ambiguous to decide the core scope, user-facing behavior, or success criteria, ask for clarification.
- If you can complete the artifact with reasonable assumptions, do so and record those assumptions or Unknowns in the artifact.
- To ask the user, output only this JSON object and no Markdown:
{"name":"ask_user_question","arguments":{"questions":[{"header":"Short topic","question":"What do you need from the user?"}]}}
- Ask at most two concise questions at once.
- After the user replies, their reply will be provided in the next prompt.
- If you are not asking the user, output only the requested artifact content."""


def initial_steps() -> list[dict[str, Any]]:
    return [
        {
            "key": step.key,
            "title": step.title,
            "kind": step.kind,
            "status": "pending",
            "started_at": None,
            "ended_at": None,
            "error": None,
            "retry_count": 0,
        }
        for step in STEPS
    ]


class EventBus:
    def __init__(self) -> None:
        self.queues: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self.queues.get(run_id, set())):
            await queue.put(event)

    async def subscribe(self, run_id: str):
        queue: asyncio.Queue = asyncio.Queue()
        self.queues.setdefault(run_id, set()).add(queue)
        try:
            yield queue
        finally:
            self.queues.get(run_id, set()).discard(queue)


bus = EventBus()
running_tasks: dict[str, asyncio.Task] = {}
running_processes: dict[str, asyncio.subprocess.Process] = {}


class QwenCliClient:
    def __init__(self) -> None:
        settings = load_settings()["qwen"]
        self.bin = os.environ.get("QWEN_BIN") or self._default_bin()
        self.timeout_sec = int(os.environ.get("QWEN_TIMEOUT_SEC", "1200"))
        self.mock = os.environ.get("QWEN_MOCK", "").lower() in {"1", "true", "yes"}
        env_reuse = os.environ.get("QWEN_REUSE_SESSION")
        self.reuse_session = (
            env_reuse.lower() not in {"0", "false", "no"}
            if env_reuse is not None
            else bool(settings.get("reuse_session", False))
        )
        self.bare = os.environ.get("QWEN_BARE", "0").lower() in {"1", "true", "yes"}
        self.auth_type = (os.environ.get("QWEN_AUTH_TYPE") or settings.get("auth_type") or "").strip()

    def _default_bin(self) -> str:
        if os.name == "nt":
            return shutil.which("qwen.cmd") or shutil.which("qwen.exe") or "qwen.cmd"
        return "qwen"

    def command(self, qwen_session_id: str | None = None, include_prompt_flag: bool = True) -> list[str]:
        cmd = [self.bin]
        if self.bare:
            cmd.append("--bare")
        if self.reuse_session and qwen_session_id:
            cmd.extend(["--session-id", qwen_session_id, "--chat-recording"])
        if self.auth_type:
            cmd.extend(["--auth-type", self.auth_type])
        if include_prompt_flag:
            cmd.append("-p")
        return cmd

    def run(self, prompt: str, cwd: Path, qwen_session_id: str | None = None, timeout_sec: int | None = None) -> str:
        if self.mock:
            return mock_qwen_response(prompt)
        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")
        try:
            proc = subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False),
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if qwen_session_id and "already in use" in stderr:
                return self.run(prompt, cwd, None, timeout_sec)
            raise WorkflowError(proc.stderr.strip() or f"Qwen CLI failed with exit code {proc.returncode}.")
        return proc.stdout.strip()

    async def run_stream(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None = None,
        timeout_sec: int | None = None,
        on_output=None,
        run_id: str | None = None,
    ) -> str:
        if self.mock:
            output = mock_qwen_response(prompt)
            if on_output:
                for line in output.splitlines():
                    await on_output("stdout", line)
                    await asyncio.sleep(0.02)
            return output
        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")

        proc = await asyncio.create_subprocess_exec(
            *self.command(qwen_session_id, include_prompt_flag=False),
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if run_id:
            running_processes[run_id] = proc
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        async def read_stream(stream, label: str, parts: list[str]) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace")
                parts.append(text)
                if on_output:
                    await on_output(label, text.rstrip("\r\n"))

        readers = [
            asyncio.create_task(read_stream(proc.stdout, "stdout", stdout_parts)),
            asyncio.create_task(read_stream(proc.stderr, "stderr", stderr_parts)),
        ]
        try:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=timeout_sec or self.timeout_sec)
            await asyncio.gather(*readers)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            for task in readers:
                task.cancel()
            raise WorkflowError(f"Qwen CLI timed out after {timeout_sec or self.timeout_sec} seconds.") from exc
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            for task in readers:
                task.cancel()
            raise
        finally:
            if run_id and running_processes.get(run_id) is proc:
                running_processes.pop(run_id, None)

        stdout = "".join(stdout_parts).strip()
        stderr = "".join(stderr_parts).strip()
        if proc.returncode != 0:
            if qwen_session_id and "already in use" in stderr:
                if on_output:
                    await on_output("stderr", "Qwen session is already in use; retrying this step without --session-id.")
                return await self.run_stream(prompt, cwd, None, timeout_sec, on_output, run_id)
            raise WorkflowError(stderr or f"Qwen CLI failed with exit code {proc.returncode}.")
        if not stdout and stderr:
            raise WorkflowError(stderr)
        return stdout


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
    }


def resolve_skill_file(skill_path: str | None) -> Path | None:
    if not skill_path:
        return None
    path = Path(skill_path).expanduser()
    if path.is_dir():
        return path / "SKILL.md"
    return path


def discover_skill_files(skill_path: str | None) -> list[Path]:
    if not skill_path:
        return []
    path = Path(skill_path).expanduser()
    if path.is_file():
        return [path]
    direct = path / "SKILL.md"
    if direct.exists():
        return [direct]
    if not path.exists() or not path.is_dir():
        return []
    return sorted(child / "SKILL.md" for child in path.iterdir() if (child / "SKILL.md").exists())


def parse_skill_meta(skill_file: Path) -> dict[str, str]:
    text = read_text(skill_file)
    meta = {"name": skill_file.parent.name, "description": "", "path": str(skill_file)}
    match = re.match(r"---\s*(.*?)\s*---", text, re.DOTALL)
    if not match:
        return meta
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"name", "description"}:
            meta[key] = value.strip()
    return meta


def select_skill_files(skill_path: str | None, step_key: str, requirement: str) -> list[Path]:
    files = discover_skill_files(skill_path)
    if len(files) <= 1:
        return files
    metas = [(parse_skill_meta(skill_file), skill_file) for skill_file in files]
    exact = []
    for wanted in SKILLS_BY_STEP.get(step_key, []):
        exact.extend(skill_file for meta, skill_file in metas if meta["name"] == wanted)
    if exact:
        return exact

    keywords = re.findall(r"[a-zA-Z][a-zA-Z-]{2,}", requirement.lower())
    scored: list[tuple[int, str, Path]] = []
    for meta, skill_file in metas:
        if meta["name"] in {"interview-me", "using-agent-skills"}:
            continue
        haystack = f"{meta['name']} {meta['description']}".lower()
        score = sum(1 for keyword in keywords if keyword and keyword.lower() in haystack)
        if score:
            scored.append((score, meta["name"], skill_file))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:3]]


def load_skill_context(skill_path: str | None, step_key: str, requirement: str) -> tuple[str, list[Path]]:
    skill_files = select_skill_files(str(DEFAULT_SKILL_PATH), step_key, requirement)
    if not skill_files:
        return f"WARNING: no matching skill files found under: {DEFAULT_SKILL_PATH}", []
    chunks = []
    for skill_file in skill_files:
        chunks.append(f"<!-- Skill: {skill_file} -->\n\n{read_text(skill_file)}")
    return "\n\n---\n\n".join(chunks), skill_files


def skill_runtime_guidance(skill_files: list[Path]) -> str:
    if not skill_files:
        return ""
    names = [parse_skill_meta(path)["name"] for path in skill_files]
    lines = [
        "Selected Qwen skills were read from disk. Apply them as methodology, not as a request to call tools.",
        f"Selected skill names: {', '.join(names)}",
        "This workflow is non-interactive/headless.",
        "Never output tool-call JSON such as todo, list_directory, calculateTotal, or arbitrary name/arguments.",
        "Only output ask_user_question JSON when a missing language/stack choice for an empty project or an ambiguous core spec blocks progress.",
        "If you can proceed with reasonable assumptions, write assumptions and Unknowns in the artifact instead.",
        "The WORKFLOW STEP PROMPT below is the highest-priority output contract.",
    ]
    return "\n".join(lines)


def require_sections(text: str, sections: Iterable[str], label: str) -> None:
    missing = [section for section in sections if f"## {section}" not in text]
    if missing:
        raise ValidationError(f"{label} missing sections: {', '.join(missing)}")


def ids_with_prefix(text: str, prefix: str) -> set[str]:
    import re

    return set(re.findall(rf"\b{prefix}-\d{{3}}\b", text))


def acceptance_criteria_items(spec: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for line in spec.splitlines():
        match = re.search(r"\b(AC-\d{3})\b[:.\-\s]*(.*)", line)
        if match:
            items.append((match.group(1), match.group(2).strip() or "Acceptance criterion"))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for ac_id, text in items:
        if ac_id not in seen:
            seen.add(ac_id)
            unique.append((ac_id, text))
    return unique


def synthesize_todo_from_spec(output_dir: Path) -> str:
    spec = read_text(output_dir / "spec.md")
    ac_items = acceptance_criteria_items(spec)
    if not ac_items:
        ac_items = [("AC-001", "Complete the requested workflow requirement")]

    todo_lines = ["# Todo", "", "## Todo List"]
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TODO-{index:03d} Implement and verify {ac_id}: {text}")

    todo_lines.extend(["", "## Test Plan"])
    for index, (ac_id, text) in enumerate(ac_items, start=1):
        todo_lines.append(f"- TEST-{index:03d} Test that {ac_id} is satisfied: {text}")

    covered = ", ".join(ac_id for ac_id, _ in ac_items)
    todo_lines.extend(
        [
            "",
            "## Done Criteria",
            f"- All acceptance criteria are implemented and tested: {covered}.",
            "- The workflow can proceed through review, build, test, and final review without validation errors.",
        ]
    )
    return "\n".join(todo_lines) + "\n"


def project_file_snapshot(project_dir: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    if not project_dir.exists():
        return snapshot
    ignored_dirs = {".git", ".qwen-workflow", "__pycache__", "node_modules", ".venv", "venv"}
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.relative_to(project_dir).parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[str(path.relative_to(project_dir))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def project_has_user_files(project_dir: Path) -> bool:
    return bool(project_file_snapshot(project_dir))


def project_overview(project_dir: Path, limit: int = 180) -> str:
    snapshot = project_file_snapshot(project_dir)
    if not snapshot:
        return "Project appears empty."
    paths = sorted(snapshot)
    shown = paths[:limit]
    lines = [f"- {path}" for path in shown]
    if len(paths) > limit:
        lines.append(f"- ... {len(paths) - limit} more files")
    return "\n".join(lines)


def snapshot_changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> bool:
    return before != after


def extract_build_files(build_result: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    pattern = re.compile(r"^FILE:\s*(?P<path>.+?)\s*\r?\nCONTENT:\r?\n(?P<content>.*?)(?=^END_FILE\s*$)", re.DOTALL | re.MULTILINE)
    for match in pattern.finditer(build_result):
        rel_path = match.group("path").strip().strip("`").replace("\\", "/")
        content = match.group("content")
        content = re.sub(r"\r?\n$", "", content)
        files.append((rel_path, content + "\n"))
    return files


def apply_build_files(project_dir: Path, build_result: str) -> list[Path]:
    written: list[Path] = []
    project_root = project_dir.resolve()
    for rel_path, content in extract_build_files(build_result):
        rel = Path(rel_path)
        if rel.is_absolute() or ".." in rel.parts or ".qwen-workflow" in rel.parts:
            raise WorkflowError(f"build output contains unsafe file path: {rel_path}")
        target = (project_root / rel).resolve()
        if target != project_root and project_root not in target.parents:
            raise WorkflowError(f"build output path escapes Project Path: {rel_path}")
        write_text(target, content)
        written.append(target)
    return written


def normalized_rel_path(rel_path: str) -> str:
    return rel_path.strip().strip("`").replace("\\", "/")


def is_test_file_path(rel_path: str) -> bool:
    normalized = normalized_rel_path(rel_path)
    path = Path(normalized)
    parts = path.parts
    if not parts:
        return False
    if parts[0] != "tests":
        return False
    name = path.name
    return name == "conftest.py" or (name.startswith("test_") and name.endswith(".py"))


def validate_generated_test_files(files: list[tuple[str, str]]) -> None:
    if not files:
        raise WorkflowError("generate_tests did not create any test files. Qwen test output must include FILE/CONTENT/END_FILE blocks.")
    invalid = [rel_path for rel_path, _ in files if not is_test_file_path(rel_path)]
    if invalid:
        raise WorkflowError(
            "generate_tests can only write pytest files under tests/ "
            f"(tests/test_*.py or tests/conftest.py). Invalid file(s): {', '.join(invalid)}"
        )


def validate_build_files_are_not_tests(files: list[tuple[str, str]]) -> None:
    invalid = [rel_path for rel_path, _ in files if is_test_file_path(rel_path) or Path(normalized_rel_path(rel_path)).name.startswith("test_")]
    if invalid:
        raise WorkflowError(
            "build must not create or modify test files. Generate Tests owns tests/. "
            f"Invalid build file(s): {', '.join(invalid)}"
        )


def validate_spec(output_dir: Path) -> None:
    text = read_text(output_dir / "spec.md")
    if not text.strip():
        raise ValidationError("spec.md is empty.")
    require_sections(
        text,
        ["Goal", "Scope", "Out of Scope", "Input", "Output", "Rules", "Acceptance Criteria", "Unknowns"],
        "spec.md",
    )
    ac_ids = ids_with_prefix(text, "AC")
    if "AC-001" not in ac_ids:
        raise ValidationError("spec.md must include AC-001.")
    if len(ac_ids) != len(list(ac_ids)):
        raise ValidationError("spec.md has duplicate AC IDs.")


def validate_todo(output_dir: Path) -> None:
    spec = read_text(output_dir / "spec.md")
    todo = read_text(output_dir / "todo.md")
    if not todo.strip():
        raise ValidationError("todo.md is empty.")
    require_sections(todo, ["Todo List", "Test Plan", "Done Criteria"], "todo.md")
    if "TODO-001" not in ids_with_prefix(todo, "TODO"):
        raise ValidationError("todo.md must include TODO-001.")
    if "TEST-001" not in ids_with_prefix(todo, "TEST"):
        raise ValidationError("todo.md must include TEST-001.")
    missing = sorted(ac for ac in ids_with_prefix(spec, "AC") if ac not in todo)
    if missing:
        raise ValidationError(f"todo.md does not reference all AC IDs: {', '.join(missing)}")


def require_status(path: Path, expected: str) -> None:
    text = read_text(path)
    if f"Status: {expected}" not in text:
        raise ValidationError(f"{path.name} must contain 'Status: {expected}'.")


def artifact_record(run_id: str, run_dir: Path, rel_path: str) -> dict[str, Any]:
    path = run_dir / rel_path
    return {
        "id": f"{run_id}:{rel_path.replace('/', '|')}",
        "name": Path(rel_path).name,
        "path": rel_path,
        "size": path.stat().st_size if path.exists() else 0,
        "updated_at": utc_now(),
    }


def load_prompt(name: str, **values: str) -> str:
    template = read_text(PROMPTS_DIR / name)
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


async def update_run(run_id: str, fn) -> dict[str, Any] | None:
    def mut(data):
        for run in data["runs"]:
            if run["id"] == run_id:
                fn(run)
                return run
        return None

    return await store.mutate(mut)


async def get_run_record(run_id: str) -> dict[str, Any]:
    data = await store.read()
    run = next((item for item in data["runs"] if item["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def append_session_message(session_id: str, role: str, content: str) -> dict[str, Any]:
    msg = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": utc_now(),
    }

    def add(data):
        data["messages"].append(msg)
        for session in data.get("sessions", []):
            if session.get("id") == session_id:
                session["updated_at"] = utc_now()
        return msg

    return await store.mutate(add)


async def log(run: dict[str, Any], message: str) -> None:
    line = f"[{utc_now()}] {message}"
    run_dir = Path(run["workspace"])
    write_text(run_dir / ".workflow" / "run-log.md", read_text(run_dir / ".workflow" / "run-log.md") + line + "\n")
    await bus.publish(run["id"], {"type": "log", "message": line})


async def set_step(run_id: str, key: str, status: str, error: str | None = None) -> None:
    def apply(run):
        for step in run["steps"]:
            if step["key"] == key:
                step["status"] = status
                if status == "running":
                    step["started_at"] = utc_now()
                    step["error"] = None
                if status in {"passed", "failed", "skipped", "waiting_input", "cancelled"}:
                    step["ended_at"] = utc_now()
                    step["error"] = error
        run["updated_at"] = utc_now()

    run = await update_run(run_id, apply)
    if run:
        await bus.publish(run_id, {"type": "run", "run": run})


async def reset_steps_from(run_id: str, start_index: int) -> dict[str, Any] | None:
    def apply(run):
        for index, step in enumerate(run["steps"]):
            if index >= start_index:
                step["status"] = "pending"
                step["started_at"] = None
                step["ended_at"] = None
                step["error"] = None
        run["status"] = "queued"
        run["error"] = None
        run["ended_at"] = None
        run["updated_at"] = utc_now()

    return await update_run(run_id, apply)


async def increment_step_retry(run_id: str, key: str) -> int:
    def apply(run):
        for step in run["steps"]:
            if step["key"] == key:
                step["retry_count"] = int(step.get("retry_count", 0)) + 1
                return step["retry_count"]
        return 0

    result = await store.mutate(lambda data: apply(next(run for run in data["runs"] if run["id"] == run_id)))
    run = await get_run_record(run_id)
    await bus.publish(run_id, {"type": "run", "run": run})
    return int(result or 0)


async def refresh_artifacts(run_id: str) -> None:
    def apply(run):
        run_dir = Path(run["workspace"])
        rels = [
            "requirement.md",
            "input/questions.md",
            "input/answers.md",
            "input/guidance.md",
            "prompts/skill-context.md",
            "prompts/prepare_project.md",
            "prompts/generate_spec.md",
            "prompts/repair_spec.md",
            "prompts/review_spec.md",
            "prompts/generate_todo.md",
            "prompts/repair_todo.md",
            "prompts/review_todo.md",
            "prompts/generate_tests.md",
            "prompts/build.md",
            "prompts/final_review.md",
            "output/architecture.md",
            "output/spec.raw.md",
            "output/spec.md",
            "output/spec-review.md",
            "output/todo.raw.md",
            "output/todo.md",
            "output/todo-review.md",
            "output/build-result.md",
            "output/test-plan.md",
            "output/test-result.md",
            "output/final-review.md",
            ".workflow/run-log.md",
            ".workflow/state.json",
        ]
        run["artifacts"] = [artifact_record(run["id"], run_dir, rel) for rel in rels if (run_dir / rel).exists()]
        run["updated_at"] = utc_now()

    run = await update_run(run_id, apply)
    if run:
        await bus.publish(run_id, {"type": "run", "run": run})


async def run_qwen_step(run: dict[str, Any], step_key: str, prompt_name: str, artifact: str) -> None:
    output_dir = Path(run["workspace"]) / "output"
    input_dir = Path(run["workspace"]) / "input"
    settings = load_settings()["qwen"]
    requirement = read_text(Path(run["workspace"]) / "requirement.md")
    answers = read_text(input_dir / "answers.md")
    guidance = read_text(input_dir / "guidance.md")
    project_dir = Path(run.get("project_path") or ROOT)
    architecture = read_text(project_dir / "architecture.md")
    skill_context, skill_files = load_skill_context(str(DEFAULT_SKILL_PATH), step_key, requirement)
    prompt = load_prompt(
        prompt_name,
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
        project_path=run.get("project_path", ""),
        workspace_path=run.get("workspace", ""),
    )
    if answers.strip() and "{{answers}}" not in read_text(PROMPTS_DIR / prompt_name):
        prompt = (
            f"{prompt}\n\n"
            "User replies from previous workflow interaction:\n\n"
            f"{answers.strip()}\n"
        )
    if guidance.strip() and "{{guidance}}" not in read_text(PROMPTS_DIR / prompt_name):
        prompt = (
            f"{prompt}\n\n"
            "User step guidance added during the workflow:\n\n"
            f"{guidance.strip()}\n"
        )
    if architecture.strip() and step_key != "prepare_project" and "{{architecture}}" not in read_text(PROMPTS_DIR / prompt_name):
        prompt = (
            f"{prompt}\n\n"
            "Current project architecture context from architecture.md:\n\n"
            f"{architecture.strip()}\n"
        )
    prompt = f"{prompt}\n\n{interaction_instruction()}"
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
        if step_key not in USER_QUESTION_ALLOWED_STEPS:
            raise WorkflowError(
                f"{step_key}: Qwen asked for user input outside allowed clarification steps. "
                "Only prepare/spec steps may ask; later steps must use assumptions, Unknowns, or fail with a concrete artifact."
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

    await run_qwen_step(run, "repair_spec", "08_repair_spec.md", "spec.md")
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


async def prepare_project_step(run: dict[str, Any]) -> None:
    project_dir = Path(run.get("project_path") or ROOT)
    architecture_path = project_dir / "architecture.md"
    if not project_has_user_files(project_dir) and not architecture_path.exists():
        await log(run, f"prepare_project: working directory appears empty, skipping architecture discovery for {project_dir}")
        write_text(Path(run["workspace"]) / "output" / "architecture.md", "Status: SKIPPED\n\nProject appears empty.\n")
        await refresh_artifacts(run["id"])
        return

    before = read_text(architecture_path)
    await run_qwen_step(run, "prepare_project", "00_prepare.md", "architecture.md")
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
    command = run.get("test_command") or os.environ.get("WORKFLOW_TEST_COMMAND", "python -m pytest")
    run_dir = Path(run["workspace"])
    test_cwd = Path(run.get("project_path") or ROOT)
    await log(run, f"run_test: executing `{command}` in {test_cwd}")

    def execute() -> subprocess.CompletedProcess:
        return subprocess.run(command, cwd=str(test_cwd), shell=True, capture_output=True, text=True, encoding="utf-8")

    proc = await asyncio.to_thread(execute)
    result = f"Command: {command}\nExitCode: {proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n"
    write_text(run_dir / "output" / "test-result.md", result)
    await refresh_artifacts(run["id"])
    if proc.returncode != 0:
        raise WorkflowError(f"Test command failed with exit code {proc.returncode}.")


async def generate_tests_step(run: dict[str, Any]) -> None:
    await run_qwen_step(run, "generate_tests", "07_test.md", "test-plan.md")
    project_dir = Path(run.get("project_path") or ROOT)
    test_plan = read_text(Path(run["workspace"]) / "output" / "test-plan.md")
    files = extract_build_files(test_plan)
    validate_generated_test_files(files)
    written = apply_build_files(project_dir, test_plan)
    if written:
        await log(run, "generate_tests: materialized test files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
    else:
        await log(run, "generate_tests: no FILE/CONTENT/END_FILE test files found in output/test-plan.md")
        raise WorkflowError("generate_tests did not create any test files. Qwen test output must include FILE/CONTENT/END_FILE blocks.")


async def build_step(run: dict[str, Any]) -> None:
    project_dir = Path(run.get("project_path") or ROOT)
    before = project_file_snapshot(project_dir)
    await run_qwen_step(run, "build", "05_build.md", "build-result.md")
    build_result = read_text(Path(run["workspace"]) / "output" / "build-result.md")
    validate_build_files_are_not_tests(extract_build_files(build_result))
    written = apply_build_files(project_dir, build_result)
    if written:
        await log(run, "build: materialized files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
    after = project_file_snapshot(project_dir)
    if not snapshot_changed(before, after):
        raise WorkflowError(
            f"build did not create or modify files under Project Path: {project_dir}. "
            "Qwen build output must include FILE/CONTENT/END_FILE blocks."
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

        actions = [
            ("prepare_project", lambda: prepare_project_step(run)),
            ("generate_spec", lambda: run_qwen_step(run, "generate_spec", "01_spec.md", "spec.md")),
            ("validate_spec", lambda: validate_or_repair_spec(run, output_dir)),
            ("review_spec", lambda: run_qwen_step(run, "review_spec", "02_review_spec.md", "spec-review.md")),
            ("spec_gate", lambda: asyncio.to_thread(require_status, output_dir / "spec-review.md", "PASS")),
            ("generate_todo", lambda: run_qwen_step(run, "generate_todo", "03_todo.md", "todo.md")),
            ("validate_todo", lambda: validate_or_repair_todo(run, output_dir)),
            ("review_todo", lambda: run_qwen_step(run, "review_todo", "04_review_todo.md", "todo-review.md")),
            ("todo_gate", lambda: asyncio.to_thread(require_status, output_dir / "todo-review.md", "PASS")),
            ("generate_tests", lambda: generate_tests_step(run)),
            ("build", lambda: build_step(run)),
            ("run_test", lambda: run_tests(run)),
            ("final_review", lambda: run_qwen_step(run, "final_review", "06_final_review.md", "final-review.md")),
            ("final_gate", lambda: asyncio.to_thread(require_status, output_dir / "final-review.md", "PASS")),
        ]
        key_to_index = {key: index for index, (key, _) in enumerate(actions)}
        max_retries = int(load_settings()["qwen"].get("max_retries", 2))
        index = start_index
        while index < len(actions):
            key, action = actions[index]
            try:
                await step(key, action)
                index += 1
            except UserInputRequired:
                raise
            except Exception as exc:
                retry_key = RETRY_FROM.get(key)
                if retry_key is None:
                    raise
                retry_count = await increment_step_retry(run_id, retry_key)
                if retry_count > max_retries:
                    await log(run, f"{key}: max retries reached for {retry_key}: {exc}")
                    raise
                target_index = key_to_index[retry_key]
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
        await log(run, f"workflow: failed: {exc}")

        def fail(r):
            r["status"] = "failed"
            r["error"] = str(exc)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        failed_run = await update_run(run_id, fail)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(failed_run, indent=2, ensure_ascii=False))
        await refresh_artifacts(run_id)
        await bus.publish(run_id, {"type": "failed", "error": str(exc)})


