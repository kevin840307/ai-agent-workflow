from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text
from app.workflow_runtime.agent_safety import write_agent_safety_report
from app.workflow_runtime.event_log import append_event
from app.workflow_runtime.run_artifacts import write_standard_run_artifacts
from app.workflow_runtime.trace import write_run_trace_artifacts


def repair_run_artifacts(run: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the standardized artifact layout from the best available run state."""
    run_dir = Path(run["workspace"])
    wf = run_dir / ".workflow"
    wf.mkdir(parents=True, exist_ok=True)
    repaired: list[str] = []
    warnings: list[str] = []

    state_path = wf / "state.json"
    if not state_path.exists():
        write_text(state_path, json.dumps(run, indent=2, ensure_ascii=False))
        repaired.append("state.json")

    events_path = wf / "events.jsonl"
    if not events_path.exists() or not read_text(events_path).strip():
        append_event(run, "artifact.repaired", message="Artifact repair initialized missing event log.", status=run.get("status"))
        repaired.append("events.jsonl")

    try:
        write_run_trace_artifacts(run, run_dir)
        repaired.append("run-trace")
    except Exception as exc:
        warnings.append(f"run trace repair failed: {exc}")

    try:
        write_agent_safety_report(run)
        repaired.append("agent-safety-report")
    except Exception as exc:
        warnings.append(f"agent safety report repair failed: {exc}")

    index = write_standard_run_artifacts(run, run_dir)
    repaired.append("artifact-index")
    report = {
        "schema": "aiwf.artifact-repair.v1",
        "run_id": run.get("id"),
        "status": "PASS" if not warnings else "WARN",
        "repaired_at": utc_now(),
        "repaired": sorted(set(repaired)),
        "warnings": warnings,
        "artifact_index_schema": index.get("schema"),
        "artifact_count": len(index.get("records") or []),
    }
    write_text(wf / "artifact-repair-report.json", json.dumps(report, indent=2, ensure_ascii=False))
    write_text(wf / "artifact-repair-report.md", render_artifact_repair_report(report))
    return report


def render_artifact_repair_report(report: dict[str, Any]) -> str:
    lines = [
        "# Artifact Repair Report",
        "",
        f"- Run ID: {report.get('run_id')}",
        f"- Status: {report.get('status')}",
        f"- Repaired At: {report.get('repaired_at')}",
        f"- Artifact Count: {report.get('artifact_count')}",
        "",
        "## Repaired Items",
    ]
    for item in report.get("repaired") or []:
        lines.append(f"- {item}")
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        for warning in report.get("warnings") or []:
            lines.append(f"- {warning}")
    return "\n".join(lines).rstrip() + "\n"
