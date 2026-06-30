from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.paths import read_text, write_text


def write_run_trace_artifacts(run: dict[str, Any], run_dir: Path) -> None:
    workflow_dir = run_dir / ".workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    trace = build_run_trace(run, run_dir)
    write_text(workflow_dir / "run-trace.json", json.dumps(trace, indent=2, ensure_ascii=False))
    write_text(workflow_dir / "run-summary.md", render_run_summary(trace))


def build_run_trace(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    log_text = read_text(run_dir / ".workflow" / "run-log.md")
    steps = [_step_trace(step, run_dir) for step in run.get("steps", [])]
    return {
        "run_id": run.get("id"),
        "session_id": run.get("session_id"),
        "status": run.get("status"),
        "error": run.get("error"),
        "error_code": run.get("error_code"),
        "workflow_id": run.get("workflow_id"),
        "workflow_name": run.get("workflow_name"),
        "project_path": run.get("project_path"),
        "workspace": run.get("workspace"),
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "duration_ms": _duration_ms(run.get("started_at"), run.get("ended_at")),
        "agent_session_ids": run.get("agent_session_ids") or {},
        "step_count": len(steps),
        "passed_steps": sum(1 for step in steps if step.get("status") == "passed"),
        "failed_steps": sum(1 for step in steps if step.get("status") == "failed"),
        "total_retries": sum(int(step.get("retry_count") or 0) for step in steps),
        "steps": steps,
        "project_changes": _project_changes_from_log(log_text),
        "artifacts": [
            {
                "name": artifact.get("name"),
                "path": artifact.get("path"),
                "size": artifact.get("size"),
            }
            for artifact in run.get("artifacts", [])
            if not str(artifact.get("path") or "").startswith(".workflow/run-")
        ],
        "timeline": run.get("timeline") or [],
    }


def render_run_summary(trace: dict[str, Any]) -> str:
    status = str(trace.get("status") or "unknown").upper()
    lines = [
        "# Run Summary",
        "",
        f"- Status: {status}",
        f"- Workflow: {trace.get('workflow_name') or trace.get('workflow_id') or 'unknown'}",
        f"- Run ID: {trace.get('run_id')}",
        f"- Project Path: {trace.get('project_path')}",
        f"- Duration: {_format_duration(trace.get('duration_ms'))}",
        f"- Steps: {trace.get('passed_steps', 0)}/{trace.get('step_count', 0)} passed",
        f"- Retries: {trace.get('total_retries', 0)}",
    ]
    if trace.get("error_code") or trace.get("error"):
        lines.extend(
            [
                f"- Error Code: {trace.get('error_code') or 'UNKNOWN'}",
                f"- Error: {trace.get('error') or ''}",
            ]
        )

    lines.extend(["", "## Steps"])
    for step in trace.get("steps") or []:
        title = step.get("title") or step.get("key")
        suffix = f", retry {step.get('retry_count')}" if step.get("retry_count") else ""
        lines.append(f"- {title}: {step.get('status')}{suffix}, {_format_duration(step.get('duration_ms'))}")
        if step.get("error_code") or step.get("error"):
            lines.append(f"  - Error: {step.get('error_code') or 'UNKNOWN'} {step.get('error') or ''}".rstrip())

    lines.extend(["", "## Project Changes"])
    changes = trace.get("project_changes") or []
    if changes:
        lines.extend(f"- {item}" for item in changes)
    else:
        lines.append("- No project file changes were detected in run logs.")

    lines.extend(["", "## Key Artifacts"])
    artifacts = trace.get("artifacts") or []
    if artifacts:
        for artifact in artifacts:
            lines.append(f"- {artifact.get('path')} ({artifact.get('size', 0)} bytes)")
    else:
        lines.append("- No artifacts recorded.")

    lines.extend(["", "## Reproduce"])
    lines.append(f"- Inspect prompt files under `{trace.get('workspace')}/prompts`.")
    lines.append("- Inspect raw trace at `.workflow/run-trace.json`.")
    return "\n".join(lines).rstrip() + "\n"


def _step_trace(step: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    config = step.get("config") or {}
    key = step.get("key")
    prompt_path = f"prompts/{key}.md" if key else ""
    output_file = str(config.get("outputFile") or config.get("filename") or "").strip()
    output_path = f"output/{output_file}" if output_file and not output_file.startswith(("output/", "input/", "prompts/", ".workflow/")) else output_file
    return {
        "key": key,
        "title": step.get("title"),
        "kind": step.get("kind"),
        "type": step.get("type"),
        "agent": step.get("agent") or config.get("agent") or config.get("provider") or "",
        "status": step.get("status"),
        "started_at": step.get("started_at"),
        "ended_at": step.get("ended_at"),
        "duration_ms": _duration_ms(step.get("started_at"), step.get("ended_at")),
        "retry_count": int(step.get("retry_count") or 0),
        "retry_from_step_key": step.get("retry_from_step_key") or config.get("retryFromStepKey") or "",
        "error": step.get("error"),
        "error_code": step.get("error_code"),
        "prompt_path": prompt_path if (run_dir / prompt_path).exists() else "",
        "prompt_chars": _file_chars(run_dir / prompt_path),
        "output_path": output_path,
        "output_chars": _file_chars(run_dir / output_path) if output_path else 0,
        "events": step.get("events") or [],
    }


def _duration_ms(start: Any, end: Any) -> int | None:
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if not start_dt or not end_dt:
        return None
    return max(0, int((end_dt - start_dt).total_seconds() * 1000))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _file_chars(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return len(read_text(path))


def _project_changes_from_log(log_text: str) -> list[str]:
    changes: list[str] = []
    patterns = [
        r"build: materialized files:\s*(.+)",
        r"generate_tests: materialized test files:\s*(.+)",
        r"prepare_project: architecture\.md updated",
        r"prepare_project: wrote architecture\.md",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, log_text):
            value = match.group(1).strip() if match.groups() else "architecture.md"
            for item in value.split(","):
                cleaned = item.strip()
                if cleaned and cleaned not in changes:
                    changes.append(cleaned)
    return changes


def _format_duration(duration_ms: Any) -> str:
    if duration_ms is None:
        return "unknown"
    seconds = int(duration_ms) / 1000
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    return f"{minutes}m {seconds - minutes * 60:.1f}s"
