from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.paths import read_text, write_text
from .failure_diagnosis import diagnose_agent_failure
from .failure_classifier import classify_failure
from .run_diff import write_run_diff_artifacts
from .run_console import build_run_console
from .patch_approval import write_patch_artifacts
from .versioning import build_version_metadata
from .run_artifacts import write_standard_run_artifacts
from .step_metadata import is_validation_step, step_phase


def write_run_trace_artifacts(run: dict[str, Any], run_dir: Path) -> None:
    workflow_dir = run_dir / ".workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    trace = build_run_trace(run, run_dir)
    write_text(workflow_dir / "run-trace.json", json.dumps(trace, indent=2, ensure_ascii=False))
    write_text(workflow_dir / "run-summary.md", render_run_summary(trace))
    write_text(workflow_dir / "gate-report.json", json.dumps(build_gate_report(trace), indent=2, ensure_ascii=False))
    write_text(workflow_dir / "gate-report.md", render_gate_report(trace))
    write_text(workflow_dir / "run-console.json", json.dumps(build_run_console(run), indent=2, ensure_ascii=False))
    write_text(workflow_dir / "version-metadata.json", json.dumps(build_version_metadata(run), indent=2, ensure_ascii=False))
    write_run_diff_artifacts(run, run_dir)
    if run.get("patch_mode") in {"review", "dry_run"}:
        write_patch_artifacts(run)
    write_standard_run_artifacts(run, run_dir)


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
    lines.append("- Inspect final gate report at `.workflow/gate-report.md`.")
    return "\n".join(lines).rstrip() + "\n"



def build_gate_report(trace: dict[str, Any]) -> dict[str, Any]:
    steps = trace.get("steps") or []
    validation_steps = [step for step in steps if _is_validation_step(step)]
    review_steps = [step for step in steps if _is_review_step(step)]
    failed_steps = [step for step in steps if step.get("status") in {"failed", "waiting_input", "cancelled"}]
    validation_status = _aggregate_status(validation_steps)
    if validation_status == "SKIPPED":
        validation_status = _artifact_status(
            Path(str(trace.get("workspace") or "")) / "output" / "external-validation-result.md"
        )
    review_status = _aggregate_status(review_steps)
    final_status = "PASS" if str(trace.get("status") or "").lower() == "done" and not failed_steps else "FAIL"
    return {
        "status": final_status,
        "workflow_id": trace.get("workflow_id"),
        "run_id": trace.get("run_id"),
        "project_path": trace.get("project_path"),
        "steps_total": trace.get("step_count", 0),
        "steps_passed": trace.get("passed_steps", 0),
        "total_retries": trace.get("total_retries", 0),
        "validation_status": validation_status,
        "review_status": review_status,
        "failed_steps": [{"key": s.get("key"), "title": s.get("title"), "error": s.get("error"), "diagnosis": diagnose_agent_failure(s.get("error"), step_key=s.get("key"), error_code=s.get("error_code")), "failure_class": classify_failure(s.get("error"), step_key=s.get("key"), error_code=s.get("error_code"))} for s in failed_steps],
        "changed_files": trace.get("project_changes") or [],
        "artifacts": trace.get("artifacts") or [],
    }


def render_gate_report(trace: dict[str, Any]) -> str:
    report = build_gate_report(trace)
    lines = [
        "# Gate Report",
        "",
        f"- Status: {report['status']}",
        f"- Workflow: {trace.get('workflow_name') or trace.get('workflow_id') or 'unknown'}",
        f"- Run ID: {trace.get('run_id')}",
        f"- Review: {report['review_status']}",
        f"- Validation: {report['validation_status']}",
        f"- Retries: {report['total_retries']}",
        "",
        "## Step Timeline",
    ]
    for step in trace.get("steps") or []:
        files = step.get("changed_files") or []
        file_suffix = f"; changed: {', '.join(files[:5])}" if files else ""
        lines.append(f"- {step.get('key')}: {step.get('status')} ({_format_duration(step.get('duration_ms'))}){file_suffix}")
        if step.get("error"):
            lines.append(f"  - Error: {step.get('error')}")
            diagnosis = step.get("failure_diagnosis") or {}
            if diagnosis.get("code"):
                lines.append(f"  - Diagnosis: {diagnosis.get('code')} - {diagnosis.get('title')}")
    lines.extend(["", "## Changed Files"])
    if report["changed_files"]:
        lines.extend(f"- `{item}`" for item in report["changed_files"])
    else:
        lines.append("- No project file changes were detected in run logs.")
    if report["failed_steps"]:
        lines.extend(["", "## Failures"])
        for item in report["failed_steps"]:
            lines.append(f"- {item.get('key')}: {item.get('error') or 'failed'}")
    lines.extend(["", "## Evidence"])
    lines.append("- Raw trace: `.workflow/run-trace.json`")
    lines.append("- Effective prompts: `prompts/*.effective.md`")
    lines.append("- Prompt metadata: `prompts/*.prompt-meta.json`")
    return "\n".join(lines).rstrip() + "\n"


def _artifact_status(path: Path) -> str:
    text = read_text(path).lower()
    if not text.strip():
        return "SKIPPED"
    if "status: fail" in text or "exit code: 1" in text or "exitcode: 1" in text:
        return "FAIL"
    if "status: pass" in text or "exit code: 0" in text or "exitcode: 0" in text:
        return "PASS"
    if "status: skipped" in text:
        return "SKIPPED"
    return "UNKNOWN"


def _aggregate_status(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "SKIPPED"
    if any(step.get("status") == "failed" for step in steps):
        return "FAIL"
    if all(step.get("status") == "passed" for step in steps):
        return "PASS"
    return "UNKNOWN"


def _is_validation_step(step: dict[str, Any]) -> bool:
    return is_validation_step(step)


def _is_review_step(step: dict[str, Any]) -> bool:
    return step_phase(step) == "reviewing"


def _step_changed_files(key: str, log_text: str) -> list[str]:
    if not key:
        return []
    changes: list[str] = []
    escaped = re.escape(key)
    patterns = [
        rf"{escaped}(?:/[^:]+)?: accepted direct agent (?:production |test |)?edit\(s\):\s*(.+)",
        rf"{escaped}(?:/[^:]+)?: accepted project test file\(s\):\s*(.+)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, log_text):
            for item in match.group(1).split(","):
                cleaned = item.strip()
                if cleaned and cleaned not in changes:
                    changes.append(cleaned)
    return changes

def _step_trace(step: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    config = step.get("config") or {}
    key = step.get("key")
    prompt_path = f"prompts/{key}.md" if key else ""
    effective_prompt_path = f"prompts/{key}.effective.md" if key else ""
    prompt_meta_path = f"prompts/{key}.prompt-meta.json" if key else ""
    output_file = str(config.get("outputFile") or config.get("filename") or "").strip()
    output_path = f"output/{output_file}" if output_file and not output_file.startswith(("output/", "input/", "prompts/", ".workflow/")) else output_file
    changed_files = _step_changed_files(key, read_text(run_dir / ".workflow" / "run-log.md")) if key else []
    retry_policy = config.get("retryPolicy") or step.get("retryPolicy") or {}
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
        "retry_from_step_key": step.get("retry_from_step_key") or config.get("retryFromStepKey") or (retry_policy.get("defaultRetryTo") if isinstance(retry_policy, dict) else "") or "",
        "retry_policy": retry_policy if isinstance(retry_policy, dict) else {},
        "changed_files": changed_files,
        "error": step.get("error"),
        "error_code": step.get("error_code"),
        "failure_diagnosis": diagnose_agent_failure(step.get("error"), step_key=key, error_code=step.get("error_code")) if step.get("error") else {},
        "failure_class": classify_failure(step.get("error"), step_key=key, error_code=step.get("error_code")) if step.get("error") else {},
        "prompt_path": prompt_path if (run_dir / prompt_path).exists() else "",
        "prompt_chars": _file_chars(run_dir / prompt_path),
        "effective_prompt_path": effective_prompt_path if (run_dir / effective_prompt_path).exists() else "",
        "effective_prompt_chars": _file_chars(run_dir / effective_prompt_path),
        "prompt_meta_path": prompt_meta_path if (run_dir / prompt_meta_path).exists() else "",
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
        r"auto_generation(?:/[^:]+)?: accepted direct agent edit\(s\):\s*(.+)",
        r"build(?:/[^:]+)?: accepted direct agent edit\(s\):\s*(.+)",
        r"build(?:/[^:]+)?: accepted direct agent production edit\(s\):\s*(.+)",
        r"generate_tests(?:/[^:]+)?: accepted project test file\(s\):\s*(.+)",
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
