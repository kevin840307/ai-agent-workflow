from __future__ import annotations

import os
import shutil
import socket
import urllib.parse
from pathlib import Path
from typing import Any


def _command_available(command: str, project: Path) -> bool:
    value = str(command or "").strip()
    if not value:
        return False
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.exists()
    local = project / candidate
    return local.exists() or bool(shutil.which(value))


def _tcp_reachable(raw: str, timeout_sec: float = 1.0) -> bool:
    value = str(raw or "").strip()
    if not value:
        return False
    parsed = urllib.parse.urlparse(value if "://" in value else f"tcp://{value}")
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def inspect_environment(project_path: str | Path, profile: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate only profile-declared and plan-derived environment needs."""
    project = Path(project_path).expanduser().resolve()
    profile = profile or {}
    environment = profile.get("environment") if isinstance(profile.get("environment"), dict) else {}
    phase_commands = [
        str((phase.get("command") or [""])[0])
        for phase in profile.get("phases") or []
        if isinstance(phase, dict) and phase.get("command")
    ]
    required_commands = list(dict.fromkeys([
        *[str(item) for item in environment.get("requiredCommands") or environment.get("required_commands") or []],
        *phase_commands,
    ]))
    required_env = list(dict.fromkeys(str(item) for item in environment.get("requiredEnvironmentVariables") or environment.get("required_environment_variables") or []))
    services = list(environment.get("services") or environment.get("requiredServices") or environment.get("required_services") or [])

    command_rows = [{"command": item, "available": _command_available(item, project)} for item in required_commands]
    env_rows = [{"name": item, "available": bool(os.environ.get(item))} for item in required_env]
    service_rows: list[dict[str, Any]] = []
    for raw in services:
        item = raw if isinstance(raw, dict) else {"name": str(raw), "endpoint": str(raw)}
        endpoint = str(item.get("endpoint") or item.get("url") or item.get("healthCheck") or item.get("health_check") or "")
        required = bool(item.get("required", True))
        service_rows.append({
            "name": str(item.get("name") or endpoint or "service"),
            "endpoint": endpoint,
            "required": required,
            "reachable": _tcp_reachable(endpoint) if endpoint else not required,
        })

    blockers = [
        *[f"command:{row['command']}" for row in command_rows if not row["available"]],
        *[f"environment:{row['name']}" for row in env_rows if not row["available"]],
        *[f"service:{row['name']}" for row in service_rows if row["required"] and not row["reachable"]],
    ]
    return {
        "schema": "aiwf.environment-health.v1",
        "status": "ready" if not blockers else "blocked",
        "project_path": str(project),
        "commands": command_rows,
        "environment_variables": env_rows,
        "services": service_rows,
        "blockers": blockers,
    }


__all__ = ["inspect_environment"]
