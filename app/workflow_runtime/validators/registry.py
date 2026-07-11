from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any

from .plugins import PLUGINS


def detect_validator_plans(project_path: str | Path) -> list[dict[str, Any]]:
    project = Path(project_path).expanduser().resolve()
    plans = []
    seen: set[str] = set()
    for plugin in PLUGINS:
        if plugin.id in seen or not plugin.detect(project):
            continue
        seen.add(plugin.id)
        plan = plugin.plan(project)
        plans.append(
            {
                "id": plan.id,
                "title": plan.title,
                "command": plan.command,
                "command_text": " ".join(plan.command),
                "detected_by": plan.detected_by,
                "required": plan.required,
                "category": plan.category,
                "available": bool(plan.command and (Path(plan.command[0]).exists() or shutil.which(plan.command[0]))),
            }
        )
    return plans


def primary_validator(project_path: str | Path) -> dict[str, Any] | None:
    plans = detect_validator_plans(project_path)
    priority = {"custom": -1, "python": 0, "maven": 1, "gradle": 2, "dotnet": 3, "node": 4}
    required = [item for item in plans if item.get("required")]
    candidates = required or plans
    return sorted(candidates, key=lambda item: (-1 if item.get("category") == "custom" else priority.get(item["id"], 50)))[0] if candidates else None


async def execute_validator_plan(
    project_path: str | Path,
    *,
    validator_id: str | None = None,
    timeout_sec: int = 900,
) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    plans = detect_validator_plans(project)
    plan = next((item for item in plans if item["id"] == validator_id), None) if validator_id else primary_validator(project)
    if not plan:
        return {"schema": "aiwf.validator-result.v1", "status": "skipped", "reason": "No validator detected", "project_path": str(project)}
    if not plan.get("available"):
        return {
            "schema": "aiwf.validator-result.v1",
            "status": "unavailable" if plan.get("required") else "skipped",
            "validator": plan,
            "reason": f"Command is not installed: {plan['command'][0] if plan.get('command') else 'unknown'}",
            "project_path": str(project),
        }
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    process = await asyncio.create_subprocess_exec(
        *plan["command"],
        cwd=str(project),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=max(1, int(timeout_sec)))
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {"schema": "aiwf.validator-result.v1", "status": "failed", "validator": plan, "exit_code": None, "error_code": "VALIDATION_TIMEOUT", "timeout_sec": timeout_sec, "project_path": str(project)}
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    return {
        "schema": "aiwf.validator-result.v1",
        "status": "passed" if process.returncode == 0 else "failed",
        "validator": plan,
        "exit_code": process.returncode,
        "stdout": stdout[-20000:],
        "stderr": stderr[-20000:],
        "project_path": str(project),
    }


__all__ = ["detect_validator_plans", "execute_validator_plan", "primary_validator"]
