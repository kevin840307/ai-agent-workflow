from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_workflow_stability_score(run: dict[str, Any], checks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score a workflow run using deterministic evidence.

    The score is intentionally simple and stable so it can be compared across
    mock, self-prompt, and real-agent smoke runs. It does not replace PASS/FAIL;
    it explains how healthy the run looked.
    """
    checks = checks or {}
    score = 100
    findings: list[str] = []
    steps = run.get("steps") or []
    retry_total = sum(int(step.get("retry_count") or step.get("retryCount") or 0) for step in steps if isinstance(step, dict))

    if run.get("status") != "done":
        score -= 35
        findings.append(f"run status is {run.get('status')!r}, not done")
    if retry_total:
        penalty = min(20, retry_total * 4)
        score -= penalty
        findings.append(f"workflow used {retry_total} retry attempt(s)")
    failed_steps = [str(step.get("key")) for step in steps if isinstance(step, dict) and step.get("status") == "failed"]
    if failed_steps:
        score -= min(30, len(failed_steps) * 10)
        findings.append("failed step(s): " + ", ".join(failed_steps))
    if not checks.get("source_exists", True):
        score -= 15
        findings.append("expected production source file was not created")
    if not checks.get("tests_exist", True):
        score -= 10
        findings.append("expected test file was not created")
    if not checks.get("all_functions_present", True):
        score -= 15
        findings.append("expected API/functions were missing")
    if checks.get("manual_validation_returncode", 0) != 0:
        score -= 20
        findings.append("manual validation failed")
    if not checks.get("workflow_validation_has_pass", True):
        score -= 10
        findings.append("workflow validation evidence did not show PASS")

    risk = "low"
    bounded_score = max(0, min(100, score))
    if bounded_score < 70:
        risk = "high"
    elif bounded_score < 90 or retry_total:
        risk = "medium"
    return {
        "score": bounded_score,
        "risk": risk,
        "retry_total": retry_total,
        "findings": findings or ["run completed with deterministic evidence and no retry penalty"],
    }


def write_stability_report(path: Path, workflow_id: str, result: dict[str, Any]) -> None:
    stability = result.get("stability") or {}
    lines = [
        f"# Workflow Stability Report: {workflow_id}",
        "",
        f"Status: {result.get('status')}",
        f"Score: {stability.get('score', 0)} / 100",
        f"Risk: {stability.get('risk', 'unknown')}",
        f"Retries: {stability.get('retry_total', 0)}",
        "",
        "## Findings",
    ]
    lines.extend(f"- {item}" for item in stability.get("findings") or [])
    lines.extend(["", "## Step Summary"])
    for step in result.get("steps") or []:
        lines.append(f"- {step.get('key')}: {step.get('status')} retry={step.get('retry_count', 0)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
