from __future__ import annotations

import asyncio
import json
import os
import socket
import shutil
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.paths import DEFAULT_SKILL_PATH, ROOT
from app.runtime_modules.qwen import QwenCliClient as BaseQwenCliClient
from app.runtime_modules.skills import discover_skill_files
from app.runtime_modules.errors import WorkflowError

from .settings import load_settings

AgentOutputCallback = Callable[[str, str], Awaitable[None]]


class QwenCliClient(BaseQwenCliClient):
    def __init__(self) -> None:
        super().__init__(load_settings()["qwen"])


@dataclass
class QwenServeDaemon:
    workspace: Path
    port: int
    base_url: str
    process: subprocess.Popen | None = None
    external: bool = False
    sessions: dict[str, str] = field(default_factory=dict)
    session_lock_keys: dict[str, str] = field(default_factory=dict)


qwen_serve_process: subprocess.Popen | None = None
qwen_serve_daemons: dict[str, QwenServeDaemon] = {}
qwen_serve_session_locks: dict[str, asyncio.Lock] = {}
qwen_serve_session_locks_guard = threading.Lock()
qwen_serve_status: dict[str, Any] = {
    "enabled": True,
    "running": False,
    "started": False,
    "error": None,
    "base_url": None,
    "workspace": None,
}


def _qwen_serve_command(client: QwenCliClient, workspace: Path, port: int) -> list[str]:
    return [
        client.bin,
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(port),
        "--workspace",
        str(workspace),
        "--no-web",
    ]


def qwen_serve_disabled() -> bool:
    serve_setting = os.environ.get("QWEN_SERVE")
    if serve_setting is not None:
        return serve_setting.lower() in {"0", "false", "no", "off"}
    return os.environ.get("QWEN_USE_SERVE", "0").lower() in {"0", "false", "no", "off"}


def qwen_serve_is_running() -> bool:
    global qwen_serve_process
    if qwen_serve_process and qwen_serve_process.poll() is None:
        return True
    if any((daemon.process and daemon.process.poll() is None) or daemon.external for daemon in qwen_serve_daemons.values()):
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


def _canonical_workspace(cwd: Path | str | None = None) -> Path:
    return Path(cwd or ROOT).expanduser().resolve()


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _find_free_port(preferred: int = 4170) -> int:
    if not _port_is_open(preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _headers() -> dict[str, str]:
    token = (os.environ.get("QWEN_SERVER_TOKEN") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout: float = 10) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WorkflowError(f"Qwen serve HTTP {exc.code} for {method} {url}: {detail}") from exc
    if not raw.strip():
        return {}
    return json.loads(raw)


def _health(base_url: str, timeout: float = 1) -> bool:
    try:
        _http_json("GET", f"{base_url}/health", timeout=timeout)
        return True
    except Exception:
        return False


def _capabilities(base_url: str) -> dict[str, Any] | None:
    try:
        return _http_json("GET", f"{base_url}/capabilities", timeout=2)
    except Exception:
        return None


def _workspace_matches(capabilities: dict[str, Any] | None, workspace: Path) -> bool:
    if not capabilities:
        return False
    workspace_cwd = capabilities.get("workspaceCwd")
    if not workspace_cwd:
        return False
    try:
        return Path(str(workspace_cwd)).resolve() == workspace.resolve()
    except OSError:
        return False


def _existing_default_daemon(workspace: Path) -> QwenServeDaemon | None:
    base_url = "http://127.0.0.1:4170"
    caps = _capabilities(base_url)
    if not _workspace_matches(caps, workspace):
        return None
    return QwenServeDaemon(workspace=workspace, port=4170, base_url=base_url, external=True)


def ensure_qwen_serve(cwd: Path | str | None = None) -> dict[str, Any]:
    global qwen_serve_process, qwen_serve_status
    client = QwenCliClient()
    workspace = _canonical_workspace(cwd)
    key = str(workspace)
    qwen_serve_status = {
        "enabled": not qwen_serve_disabled(),
        "running": False,
        "started": False,
        "error": None,
        "base_url": None,
        "workspace": key,
    }
    if qwen_serve_status["enabled"] is False:
        return qwen_serve_status
    if client.mock:
        qwen_serve_status.update({"enabled": False, "error": "QWEN_MOCK is enabled."})
        return qwen_serve_status
    if shutil.which(client.bin) is None:
        qwen_serve_status.update({"error": f"Qwen CLI not found: {client.bin}"})
        return qwen_serve_status

    daemon = qwen_serve_daemons.get(key)
    if daemon and (daemon.external or (daemon.process and daemon.process.poll() is None)) and _health(daemon.base_url):
        qwen_serve_process = daemon.process
        qwen_serve_status.update({"running": True, "base_url": daemon.base_url, "port": daemon.port})
        return qwen_serve_status

    external = _existing_default_daemon(workspace)
    if external:
        qwen_serve_daemons[key] = external
        qwen_serve_status.update({"running": True, "base_url": external.base_url, "port": external.port})
        return qwen_serve_status

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        port = _find_free_port(4170)
        command: list[str] | str = _qwen_serve_command(client, workspace, port)
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
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if _health(base_url):
                break
            if qwen_serve_process.poll() is not None:
                raise WorkflowError(f"qwen serve exited early with code {qwen_serve_process.returncode}")
            time.sleep(0.25)
        if not _health(base_url):
            raise WorkflowError(f"qwen serve did not become healthy at {base_url}")
        daemon = QwenServeDaemon(workspace=workspace, port=port, base_url=base_url, process=qwen_serve_process)
        qwen_serve_daemons[key] = daemon
        qwen_serve_status.update({"running": True, "started": True, "base_url": base_url, "port": port})
    except Exception as exc:
        qwen_serve_status.update({"error": str(exc)})
    return qwen_serve_status


def _daemon_or_raise(cwd: Path) -> QwenServeDaemon:
    status = ensure_qwen_serve(cwd)
    if not status.get("running") or status.get("error"):
        raise WorkflowError(status.get("error") or "Qwen serve is not running.")
    daemon = qwen_serve_daemons.get(str(_canonical_workspace(cwd)))
    if not daemon:
        raise WorkflowError("Qwen serve daemon was not registered for this workspace.")
    return daemon


def _session_key(app_session_id: str | None) -> str:
    """Map an app/project session id to exactly one qwen serve session.

    Normal chat/workflow calls always pass the project's qwen_session_id, so the
    same project keeps the same Qwen context.  A missing id is treated as an
    explicit one-off request instead of being collapsed into a shared "default"
    session, because a global default session causes unrelated runs to collide.
    """
    return app_session_id or f"__adhoc__:{uuid.uuid4()}"


def _lock_name(daemon: QwenServeDaemon, session_key: str) -> str:
    return f"{daemon.workspace.resolve()}::{session_key}"


def _session_lock(daemon: QwenServeDaemon, session_key: str) -> asyncio.Lock:
    name = _lock_name(daemon, session_key)
    with qwen_serve_session_locks_guard:
        lock = qwen_serve_session_locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            qwen_serve_session_locks[name] = lock
        return lock


def forget_qwen_serve_session(app_session_id: str | None) -> None:
    """Forget cached serve sessions for a reset/deleted app session.

    This does not kill qwen serve.  It only removes the app-session ->
    serve-session mapping so the next request creates a clean Qwen session.
    """
    if not app_session_id:
        return
    keys_to_remove: list[str] = []
    for daemon in qwen_serve_daemons.values():
        daemon.sessions.pop(app_session_id, None)
        daemon.session_lock_keys.pop(app_session_id, None)
        keys_to_remove.append(_lock_name(daemon, app_session_id))
    with qwen_serve_session_locks_guard:
        for key in keys_to_remove:
            qwen_serve_session_locks.pop(key, None)


def _session_for(daemon: QwenServeDaemon, session_key: str) -> str:
    key = session_key
    existing = daemon.sessions.get(key)
    if existing:
        return existing
    response = _http_json(
        "POST",
        f"{daemon.base_url}/session",
        {"cwd": str(daemon.workspace), "sessionScope": "thread"},
        timeout=60,
    )
    session_id = response.get("sessionId")
    if not session_id:
        raise WorkflowError(f"Qwen serve did not return sessionId: {response}")
    daemon.sessions[key] = str(session_id)
    daemon.session_lock_keys[str(session_id)] = key
    return str(session_id)


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content") or content.get("message")
        return _text_from_content(nested) if nested is not None else ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _text_from_content(item)
            if text:
                parts.append(text)
        return "".join(parts)
    return ""


def _extract_sse_text(envelope: dict[str, Any]) -> tuple[str, bool, bool]:
    """Extract assistant text from qwen serve SSE envelopes.

    Qwen serve has changed event shapes across versions.  This extractor accepts
    session_update wrappers, direct update payloads, nested message payloads, and
    token/content arrays.  It intentionally treats any text-looking assistant
    payload as streamable output, but only marks completion when the envelope has
    an explicit finished/done/idle marker.
    """
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else envelope
    update = data.get("update") if isinstance(data.get("update"), dict) else data
    message = update.get("message") if isinstance(update.get("message"), dict) else {}

    kind_parts = [
        update.get("sessionUpdate"),
        update.get("type"),
        update.get("event"),
        data.get("type") if isinstance(data, dict) else None,
        envelope.get("event"),
        envelope.get("type"),
    ]
    kind = " ".join(str(part or "") for part in kind_parts).lower()
    role = str(message.get("role") or update.get("role") or update.get("author") or "").lower()

    content = update.get("content")
    if content is None and message:
        content = message.get("content")

    text = _text_from_content(content)
    if not text:
        text = str(
            update.get("text")
            or update.get("output")
            or message.get("text")
            or message.get("output")
            or ""
        )

    is_assistant = (
        "agent_message" in kind
        or "assistant" in kind
        or "message_delta" in kind
        or "content_delta" in kind
        or role in {"assistant", "agent", "model"}
    )
    is_done = any(
        marker in kind
        for marker in (
            "done",
            "complete",
            "completed",
            "finish",
            "finished",
            "idle",
            "turn_end",
            "response_end",
            "agent_run_complete",
        )
    )
    return text if isinstance(text, str) else "", is_assistant, is_done


def _event_number(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_sse_until_stopped(
    daemon: QwenServeDaemon,
    session_id: str,
    stop_event: threading.Event,
    completed_event: threading.Event,
    state: dict[str, Any],
    state_lock: threading.Lock,
    on_event: Callable[[str, str], None] | None,
    timeout_sec: int,
) -> None:
    req = urllib.request.Request(f"{daemon.base_url}/session/{session_id}/events", headers=_headers())
    buffer: list[str] = []
    last_event_number = 0
    try:
        with urllib.request.urlopen(req, timeout=max(timeout_sec, 60)) as resp:
            while not stop_event.is_set():
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    data_lines = [item[5:].lstrip() for item in buffer if item.startswith("data:")]
                    event_lines = [item[6:].lstrip() for item in buffer if item.startswith("event:")]
                    id_lines = [item[3:].lstrip() for item in buffer if item.startswith("id:")]
                    buffer.clear()
                    if not data_lines:
                        continue
                    event_id = _event_number(id_lines[-1] if id_lines else None)
                    if event_id is not None:
                        last_event_number = event_id
                    try:
                        envelope = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        continue
                    if event_lines:
                        envelope.setdefault("event", event_lines[-1])
                    text, is_message, is_done = _extract_sse_text(envelope)
                    now = time.monotonic()
                    with state_lock:
                        state["last_event_at"] = now
                        state["last_event_id"] = last_event_number
                        if text and is_message:
                            state.setdefault("chunks", []).append(text)
                            state["last_text_at"] = now
                        if is_done:
                            state["completed"] = True
                            completed_event.set()
                    if text and on_event:
                        on_event("stdout", text)
                    continue
                buffer.append(line)
    except Exception as exc:
        with state_lock:
            state["reader_error"] = str(exc)
        if on_event and not stop_event.is_set():
            on_event("stderr", f"Qwen serve event stream ended: {exc}")


def _post_prompt_with_queue_wait(
    daemon: QwenServeDaemon,
    session_id: str,
    prompt: str,
    timeout_sec: int,
) -> dict[str, Any]:
    """Post a prompt, waiting for Qwen serve queue pressure instead of hot-looping.

    When a previous buggy run already filled Qwen serve's per-session prompt
    queue, POST /prompt returns HTTP 503 prompt_queue_full.  Retrying the whole
    workflow immediately makes the queue worse.  This local retry waits here,
    still under the app session lock, so only one prompt can be submitted at a
    time for the project session.
    """
    url = f"{daemon.base_url}/session/{session_id}/prompt"
    body = {"prompt": [{"type": "text", "text": prompt}]}
    deadline = time.monotonic() + max(float(timeout_sec), 60.0)
    attempt = 0
    last_error: WorkflowError | None = None
    while time.monotonic() < deadline:
        attempt += 1
        try:
            return _http_json("POST", url, body, timeout=timeout_sec)
        except WorkflowError as exc:
            message = str(exc)
            if "prompt_queue_full" not in message and "Prompt queue full" not in message:
                raise
            last_error = exc
            # Back off enough that queued prompts can actually drain.  Cap the
            # wait so UI remains responsive but avoid the previous 0.2s retry storm.
            time.sleep(min(2.0 + attempt * 0.5, 8.0))
    raise last_error or WorkflowError(f"Qwen serve prompt queue did not accept a prompt for session {session_id}")


async def run_prompt_via_serve(
    prompt: str,
    cwd: Path,
    app_session_id: str | None,
    *,
    on_output: AgentOutputCallback | None = None,
    timeout_sec: int | None = None,
) -> str:
    daemon = _daemon_or_raise(cwd)
    session_key = _session_key(app_session_id)
    lock = _session_lock(daemon, session_key)

    async with lock:
        session_id = await asyncio.to_thread(_session_for, daemon, session_key)
        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        completed_event = threading.Event()
        state_lock = threading.Lock()
        state: dict[str, Any] = {
            "chunks": [],
            "last_event_at": 0.0,
            "last_text_at": 0.0,
            "last_event_id": 0,
            "completed": False,
            "reader_error": "",
        }

        def emit_output(stream: str, text: str) -> None:
            if not on_output or not text:
                return
            future = asyncio.run_coroutine_threadsafe(on_output(stream, text), loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass

        stdout_buffer_lock = threading.Lock()
        stdout_buffer: list[str] = []
        stdout_last_flush = 0.0
        stdout_flush_interval = float(os.environ.get("QWEN_SERVE_OUTPUT_FLUSH_INTERVAL_SEC", "1.0"))
        stdout_flush_chars = int(os.environ.get("QWEN_SERVE_OUTPUT_FLUSH_CHARS", "800"))
        stdout_flush_min_chars = int(os.environ.get("QWEN_SERVE_OUTPUT_FLUSH_MIN_CHARS", "120"))

        def publish(stream: str, text: str) -> None:
            """Publish Qwen serve output without flooding the UI per token.

            Qwen serve SSE usually emits very small token deltas.  Forwarding
            every delta makes the console look like one word per line and can
            slow the workflow because each publish crosses from the reader
            thread back into the asyncio loop.  Keep collecting full output in
            ``state["chunks"]`` for artifact parsing, but coalesce UI stdout
            into complete lines or reasonable chunks.
            """
            nonlocal stdout_last_flush
            if not on_output or not text:
                return
            if stream != "stdout":
                emit_output(stream, text)
                return

            to_emit = ""
            with stdout_buffer_lock:
                stdout_buffer.append(text)
                combined = "".join(stdout_buffer)
                now = time.monotonic()
                has_line = "\n" in combined
                large_enough = len(combined) >= stdout_flush_chars
                timed_batch = (
                    len(combined) >= stdout_flush_min_chars
                    and now - stdout_last_flush >= stdout_flush_interval
                )
                if not (has_line or large_enough or timed_batch):
                    return

                if has_line and not large_enough:
                    cut = combined.rfind("\n") + 1
                    to_emit = combined[:cut]
                    rest = combined[cut:]
                    stdout_buffer[:] = [rest] if rest else []
                else:
                    to_emit = combined
                    stdout_buffer.clear()
                stdout_last_flush = now

            emit_output("stdout", to_emit)

        def flush_stdout_buffer() -> None:
            nonlocal stdout_last_flush
            with stdout_buffer_lock:
                if not stdout_buffer:
                    return
                to_emit = "".join(stdout_buffer)
                stdout_buffer.clear()
                stdout_last_flush = time.monotonic()
            emit_output("stdout", to_emit)

        effective_timeout = int(timeout_sec or QwenCliClient().timeout_sec)
        reader = threading.Thread(
            target=_read_sse_until_stopped,
            args=(daemon, session_id, stop_event, completed_event, state, state_lock, publish, effective_timeout),
            daemon=True,
        )
        reader.start()

        response: dict[str, Any] = {}
        try:
            response = await asyncio.to_thread(_post_prompt_with_queue_wait, daemon, session_id, prompt, effective_timeout)

            first_output_grace = float(os.environ.get("QWEN_SERVE_FIRST_OUTPUT_GRACE_SEC", "30"))
            idle_done_sec = float(os.environ.get("QWEN_SERVE_IDLE_DONE_SEC", "8"))
            hard_deadline = time.monotonic() + max(float(effective_timeout), first_output_grace)
            first_output_deadline = time.monotonic() + first_output_grace

            while time.monotonic() < hard_deadline:
                if completed_event.is_set():
                    break
                now = time.monotonic()
                with state_lock:
                    chunks = list(state.get("chunks") or [])
                    last_text_at = float(state.get("last_text_at") or 0.0)
                    reader_error = str(state.get("reader_error") or "")

                # Preferred path: Qwen serve sends an explicit completion event.
                if completed_event.is_set():
                    break

                # Fallback path for serve versions that do not emit a reliable
                # completion marker: once we have assistant text and no new text
                # arrives for a while, treat the turn as complete.  This replaces
                # the previous behavior that returned immediately after the first
                # token and caused retry storms.
                if chunks and last_text_at > 0 and now - last_text_at >= idle_done_sec:
                    break

                # If the event stream died after yielding text, do not hang.
                if chunks and reader_error:
                    break

                # No text yet: keep waiting for initial assistant output rather
                # than returning partial/empty content immediately.
                if not chunks and now > first_output_deadline:
                    break

                await asyncio.sleep(0.2)
        finally:
            stop_event.set()
            await asyncio.to_thread(reader.join, 2)
            flush_stdout_buffer()

        with state_lock:
            output = "".join(state.get("chunks") or []).strip()
            reader_error = str(state.get("reader_error") or "")
        if not output:
            output = _text_from_content(response.get("text") or response.get("output") or response.get("message") or response.get("content")).strip()
        if not output:
            stop_reason = response.get("stopReason")
            detail = f" reader_error={reader_error}" if reader_error else ""
            raise WorkflowError(f"Qwen serve returned no assistant text. stopReason={stop_reason or 'unknown'}{detail}")
        return output


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
            "daemons": [
                {
                    "workspace": daemon.workspace.as_posix(),
                    "base_url": daemon.base_url,
                    "port": daemon.port,
                    "external": daemon.external,
                    "running": daemon.external or (daemon.process is not None and daemon.process.poll() is None),
                    "session_count": len(daemon.sessions),
                }
                for daemon in qwen_serve_daemons.values()
            ],
        },
    }
