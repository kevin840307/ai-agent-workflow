from __future__ import annotations

import asyncio
import json
import os
import socket
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_paths import DEFAULT_SKILL_PATH, ROOT
from app.runtime_qwen import QwenCliClient as BaseQwenCliClient
from app.runtime_skills import discover_skill_files
from app.runtime_errors import WorkflowError

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


qwen_serve_process: subprocess.Popen | None = None
qwen_serve_daemons: dict[str, QwenServeDaemon] = {}
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
    return os.environ.get("QWEN_SERVE", "1").lower() in {"0", "false", "no", "off"}


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


def _session_for(daemon: QwenServeDaemon, app_session_id: str | None) -> str:
    key = app_session_id or "default"
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
    return str(session_id)


def _extract_sse_text(envelope: dict[str, Any]) -> tuple[str, bool]:
    if envelope.get("type") != "session_update":
        return "", False
    data = envelope.get("data") or {}
    update = data.get("update") or data
    kind = update.get("sessionUpdate")
    content = update.get("content") or {}
    text = content.get("text") if isinstance(content, dict) else ""
    if not isinstance(text, str):
        text = ""
    return text, kind == "agent_message_chunk"


def _read_sse_until_done(
    daemon: QwenServeDaemon,
    session_id: str,
    done,
    chunks: list[str],
    on_event: Callable[[str, str], None] | None,
    timeout_sec: int,
) -> None:
    req = urllib.request.Request(f"{daemon.base_url}/session/{session_id}/events", headers=_headers())
    buffer: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=max(timeout_sec, 60)) as resp:
            while not done.is_set():
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    data_lines = [item[5:].lstrip() for item in buffer if item.startswith("data:")]
                    buffer.clear()
                    if not data_lines:
                        continue
                    try:
                        envelope = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        continue
                    text, is_message = _extract_sse_text(envelope)
                    if text:
                        if is_message:
                            chunks.append(text)
                        if on_event:
                            on_event("stdout", text)
                    continue
                buffer.append(line)
    except Exception as exc:
        if on_event and not done.is_set():
            on_event("stderr", f"Qwen serve event stream ended: {exc}")


async def run_prompt_via_serve(
    prompt: str,
    cwd: Path,
    app_session_id: str | None,
    *,
    on_output: AgentOutputCallback | None = None,
    timeout_sec: int | None = None,
) -> str:
    daemon = _daemon_or_raise(cwd)
    session_id = await asyncio.to_thread(_session_for, daemon, app_session_id)
    loop = asyncio.get_running_loop()
    done = threading.Event()
    chunks: list[str] = []

    def publish(stream: str, text: str) -> None:
        if not on_output or not text:
            return
        future = asyncio.run_coroutine_threadsafe(on_output(stream, text), loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass

    effective_timeout = timeout_sec or QwenCliClient().timeout_sec
    reader = threading.Thread(
        target=_read_sse_until_done,
        args=(daemon, session_id, done, chunks, publish, effective_timeout),
        daemon=True,
    )
    reader.start()

    def send_prompt() -> dict[str, Any]:
        return _http_json(
            "POST",
            f"{daemon.base_url}/session/{session_id}/prompt",
            {"prompt": [{"type": "text", "text": prompt}]},
            timeout=effective_timeout,
        )

    try:
        response = await asyncio.to_thread(send_prompt)
    finally:
        done.set()
        await asyncio.to_thread(reader.join, 2)

    output = "".join(chunks).strip()
    if not output:
        output = str(response.get("text") or response.get("output") or "").strip()
    if not output:
        stop_reason = response.get("stopReason")
        raise WorkflowError(f"Qwen serve returned no assistant text. stopReason={stop_reason or 'unknown'}")
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
