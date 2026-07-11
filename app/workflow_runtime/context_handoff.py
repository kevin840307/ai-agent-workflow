from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text
from app.runtime_modules.files import failure_feedback_for_step, project_overview


def _bounded(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 80)].rstrip() + "\n...[truncated by context handoff]"


def _current_task(run: dict[str, Any]) -> dict[str, Any]:
    task = run.get("_current_task")
    if isinstance(task, dict):
        return {
            "id": task.get("id"),
            "title": task.get("title"),
            "index": task.get("index"),
            "total": task.get("total"),
            "acceptance": list(task.get("acceptance") or task.get("acceptance_criteria") or [])[:20],
        }
    return {}


def build_context_handoff(
    run: dict[str, Any],
    *,
    step_key: str,
    project_dir: Path,
    workspace_path: Path,
    error: str,
) -> dict[str, Any]:
    completed_tasks = []
    for task in run.get("tasks") or []:
        if str(task.get("status") or "").lower() in {"passed", "done", "completed"}:
            completed_tasks.append({"id": task.get("id"), "title": task.get("title"), "status": task.get("status")})
    completed_steps = [
        {"key": step.get("key"), "status": step.get("status"), "retry_count": int(step.get("retry_count") or 0)}
        for step in run.get("steps") or []
        if step.get("status") in {"passed", "failed", "skipped"}
    ][-30:]
    feedback = failure_feedback_for_step(
        read_text(workspace_path / "input" / "failure-feedback.md"),
        step_key,
        latest_only=True,
    )
    validation = []
    for result in run.get("validation_results") or []:
        validation.append(
            {
                "key": result.get("key") or result.get("name"),
                "status": result.get("status"),
                "command": result.get("command"),
                "exit_code": result.get("exit_code"),
                "summary": _bounded(result.get("summary") or result.get("error") or "", 600),
            }
        )
    changed = []
    for item in run.get("file_changes") or run.get("changed_files") or []:
        if isinstance(item, str):
            changed.append({"path": item, "change": "modified"})
        elif isinstance(item, dict):
            changed.append({"path": item.get("path") or item.get("file"), "change": item.get("status") or item.get("change")})
    constraints = [
        "Continue only the current step.",
        "Re-read files from disk; never trust the previous conversation's filesystem assumptions.",
        "Keep all writes inside Project Path.",
        "Preserve completed valid work and public APIs unless the current failure requires a targeted change.",
        "Run the configured deterministic validation before claiming success.",
    ]
    payload = {
        "schema": "aiwf.context-handoff.v2",
        "created_at": utc_now(),
        "run_id": run.get("id"),
        "workflow_id": run.get("workflow_id"),
        "step_key": step_key,
        "project_path": str(project_dir),
        "requirement": _bounded(read_text(workspace_path / "requirement.md"), 4200),
        "current_task": _current_task(run),
        "completed_tasks": completed_tasks[-30:],
        "completed_steps": completed_steps,
        "changed_files": changed[-120:],
        "validation_evidence": validation[-30:],
        "latest_failure_feedback": _bounded(feedback, 2200),
        "recovery_reason": _bounded(error, 1200),
        "project_overview": _bounded(project_overview(project_dir, limit=80), 5200),
        "constraints": constraints,
        "next_action": f"Resume {step_key} in a fresh session, inspect the real files, make the smallest necessary change, and validate it.",
    }
    return payload


def render_context_handoff(payload: dict[str, Any]) -> str:
    def bullet(items: list[Any], formatter) -> list[str]:
        return [f"- {formatter(item)}" for item in items] or ["- None recorded."]

    task = payload.get("current_task") or {}
    lines = [
        "# Compact Session Handoff",
        "",
        f"Run: {payload.get('run_id')}",
        f"Workflow: {payload.get('workflow_id')}",
        f"Current step: {payload.get('step_key')}",
        f"Project Path: {payload.get('project_path')}",
        "",
        "## Goal",
        str(payload.get("requirement") or "No requirement recorded."),
        "",
        "## Current task",
        f"- {task.get('id') or 'current'}: {task.get('title') or payload.get('step_key')}",
        "",
        "## Completed work",
        *bullet(payload.get("completed_tasks") or [], lambda item: f"{item.get('id')}: {item.get('title') or ''} ({item.get('status')})"),
        "",
        "## Current changed files",
        *bullet(payload.get("changed_files") or [], lambda item: f"{item.get('path')} ({item.get('change') or 'modified'})"),
        "",
        "## Validation evidence",
        *bullet(payload.get("validation_evidence") or [], lambda item: f"{item.get('key')}: {item.get('status')} {item.get('summary') or ''}".strip()),
        "",
        "## Latest failure",
        str(payload.get("latest_failure_feedback") or payload.get("recovery_reason") or "No failure detail."),
        "",
        "## Filesystem snapshot",
        str(payload.get("project_overview") or "No project overview."),
        "",
        "## Constraints",
        *[f"- {item}" for item in payload.get("constraints") or []],
        "",
        "## Next action",
        str(payload.get("next_action") or "Continue the current step."),
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_context_handoff(
    run: dict[str, Any],
    *,
    step_key: str,
    project_dir: Path,
    workspace_path: Path,
    error: str,
) -> tuple[dict[str, Any], str]:
    payload = build_context_handoff(
        run,
        step_key=step_key,
        project_dir=project_dir,
        workspace_path=workspace_path,
        error=error,
    )
    markdown = render_context_handoff(payload)
    handoff_dir = workspace_path / "input" / "handoffs"
    safe_step = re.sub(r"[^a-zA-Z0-9_.-]+", "-", step_key).strip("-") or "step"
    sequence = len(list(handoff_dir.glob("*.json"))) + 1 if handoff_dir.exists() else 1
    stem = f"{sequence:03d}-{safe_step}"
    write_text(handoff_dir / f"{stem}.json", json.dumps(payload, indent=2, ensure_ascii=False))
    write_text(handoff_dir / f"{stem}.md", markdown)
    write_text(workspace_path / "input" / "session-handoff.json", json.dumps(payload, indent=2, ensure_ascii=False))
    write_text(workspace_path / "input" / "session-handoff.md", markdown)
    run.setdefault("context_handoffs", []).append(
        {
            "id": stem,
            "step_key": step_key,
            "created_at": payload["created_at"],
            "reason": payload["recovery_reason"],
            "path": f"input/handoffs/{stem}.json",
        }
    )
    run["context_handoffs"] = run["context_handoffs"][-20:]
    return payload, markdown


__all__ = ["build_context_handoff", "render_context_handoff", "write_context_handoff"]
