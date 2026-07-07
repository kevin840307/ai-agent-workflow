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


__all__ = ["summarize_runs"]
