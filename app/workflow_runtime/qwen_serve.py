from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from app.runtime_paths import DEFAULT_SKILL_PATH, ROOT
from app.runtime_qwen import QwenCliClient as BaseQwenCliClient
from app.runtime_skills import discover_skill_files

from .settings import load_settings


class QwenCliClient(BaseQwenCliClient):
    def __init__(self) -> None:
        super().__init__(load_settings()["qwen"])


qwen_serve_process: subprocess.Popen | None = None
qwen_serve_status: dict[str, Any] = {
    "enabled": True,
    "running": False,
    "started": False,
    "error": None,
}


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
        command: list[str] | str = _qwen_serve_command(client)
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
