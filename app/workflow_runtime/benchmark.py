from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.workflow_runtime.failure_classifier import classify_failure


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_workflow: dict[str, dict[str, Any]] = {}
    status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    failure_counts: Counter[str] = Counter()
    step_failure_counts: Counter[str] = Counter()
    step_counts: Counter[str] = Counter()
    workflow_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for run in runs:
        workflow_id = str(run.get("workflow_id") or "unknown")
        workflow_groups[workflow_id].append(run)
        if run.get("error"):
            failure_counts[classify_failure(run.get("error"), error_code=run.get("error_code")).get("code", "UNKNOWN")] += 1
        for step in run.get("steps") or []:
            step_key = str(step.get("key") or "unknown")
            step_counts[step_key] += 1
            if step.get("error") or step.get("status") in {"failed", "waiting_input", "cancelled"}:
                step_failure_counts[step_key] += 1
                failure_counts[classify_failure(step.get("error"), step_key=step_key, error_code=step.get("error_code")).get("code", "UNKNOWN")] += 1

    for workflow_id, items in workflow_groups.items():
        total = len(items)
        done = sum(1 for item in items if item.get("status") == "done")
        retries = sum(sum(int(step.get("retry_count") or 0) for step in item.get("steps") or []) for item in items)
        by_workflow[workflow_id] = {
            "runs": total,
            "done": done,
            "failed": sum(1 for item in items if item.get("status") == "failed"),
            "cancelled": sum(1 for item in items if item.get("status") == "cancelled"),
            "pass_rate": round(done / total, 4) if total else 0,
            "average_retry": round(retries / total, 3) if total else 0,
        }

    return {
        "schema": "aiwf.workflow-benchmark.v1",
        "runs_total": len(runs),
        "status_counts": dict(status_counts),
        "workflows": by_workflow,
        "failure_counts": dict(failure_counts),
        "most_common_failures": failure_counts.most_common(10),
        "step_failure_counts": dict(step_failure_counts),
        "most_unstable_steps": step_failure_counts.most_common(10),
        "step_counts": dict(step_counts),
    }


def _run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    steps = list(run.get("steps") or [])
    retries = sum(int(step.get("retry_count") or 0) for step in steps)
    validation = list(run.get("validation_results") or [])
    failures = [item for item in validation if str(item.get("status") or "").lower() in {"failed", "error", "blocked"}]
    changed = list(run.get("file_changes") or [])
    return {
        "run_id": run.get("id"),
        "workflow": run.get("workflow_id"),
        "agent": run.get("agent") or "qwen",
        "profile": run.get("run_profile"),
        "status": run.get("status"),
        "retry_count": retries,
        "step_count": len(steps),
        "validation_count": len(validation),
        "validation_failures": len(failures),
        "changed_files": len(changed),
        "manual_intervention": any(step.get("status") == "waiting_input" for step in steps),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
    }


def compare_runs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_metrics = _run_metrics(left)
    right_metrics = _run_metrics(right)
    numeric = ("retry_count", "step_count", "validation_count", "validation_failures", "changed_files")
    return {
        "schema": "aiwf.run-comparison.v1",
        "left": left_metrics,
        "right": right_metrics,
        "delta": {key: int(right_metrics[key]) - int(left_metrics[key]) for key in numeric},
        "improved": {
            "status": left_metrics["status"] != "done" and right_metrics["status"] == "done",
            "fewer_retries": right_metrics["retry_count"] < left_metrics["retry_count"],
            "fewer_validation_failures": right_metrics["validation_failures"] < left_metrics["validation_failures"],
            "less_manual_intervention": bool(left_metrics["manual_intervention"] and not right_metrics["manual_intervention"]),
        },
    }


__all__ = ["compare_runs", "summarize_runs"]
