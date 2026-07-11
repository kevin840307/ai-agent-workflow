from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.persistence.repositories import store as store_repository
from app.workflow_runtime.failure_classifier import classify_failure

TERMINAL = {"done", "failed", "cancelled"}


def _seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        return max(0.0, (datetime.fromisoformat(str(end).replace("Z", "+00:00")) - datetime.fromisoformat(str(start).replace("Z", "+00:00"))).total_seconds())
    except (TypeError, ValueError):
        return None


async def analytics_summary(limit: int = 500) -> dict[str, Any]:
    data = await store_repository.read()
    runs = list(data.get("runs") or [])[: max(1, limit)]
    terminal = [run for run in runs if run.get("status") in TERMINAL]
    completed = [run for run in terminal if run.get("status") == "done"]
    retry_values = [sum(int(step.get("retry_count") or 0) for step in run.get("steps") or []) for run in terminal]
    durations = [value for run in terminal if (value := _seconds(run.get("started_at"), run.get("ended_at"))) is not None]
    failures = Counter()
    workflows: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "done": 0, "failed": 0, "duration_total_sec": 0.0, "duration_count": 0})
    step_durations: dict[str, list[float]] = defaultdict(list)
    repairable = 0
    for run in terminal:
        workflow = str(run.get("workflow_name") or run.get("workflow_id") or "Unknown")
        row = workflows[workflow]
        row["total"] += 1
        row["done"] += int(run.get("status") == "done")
        row["failed"] += int(run.get("status") == "failed")
        duration = _seconds(run.get("started_at"), run.get("ended_at"))
        if duration is not None:
            row["duration_total_sec"] += duration
            row["duration_count"] += 1
        if run.get("status") == "failed":
            failure = classify_failure(run.get("error"), error_code=run.get("error_code"))
            failures[failure.get("code") or "UNKNOWN"] += 1
            repairable += int(bool(failure.get("auto_repairable")))
        for step in run.get("steps") or []:
            value = _seconds(step.get("started_at"), step.get("ended_at"))
            if value is not None:
                step_durations[str(step.get("key") or "step")].append(value)
    workflow_rows = []
    for name, row in workflows.items():
        total = row["total"] or 1
        workflow_rows.append({
            "workflow": name,
            "total": row["total"],
            "success_rate": round(row["done"] * 100 / total, 1),
            "failed": row["failed"],
            "avg_duration_sec": round(row["duration_total_sec"] / row["duration_count"], 1) if row["duration_count"] else None,
        })
    slow_steps = sorted(
        ({"step": key, "avg_duration_sec": round(sum(values) / len(values), 1), "samples": len(values)} for key, values in step_durations.items()),
        key=lambda item: item["avg_duration_sec"], reverse=True,
    )[:10]
    return {
        "schema": "aiwf.analytics-summary.v1",
        "runs_considered": len(runs),
        "terminal_runs": len(terminal),
        "success_rate": round(len(completed) * 100 / len(terminal), 1) if terminal else None,
        "avg_retry_count": round(sum(retry_values) / len(retry_values), 2) if retry_values else 0,
        "avg_duration_sec": round(sum(durations) / len(durations), 1) if durations else None,
        "active_runs": sum(1 for run in runs if run.get("status") not in TERMINAL),
        "auto_repairable_failures": repairable,
        "failure_distribution": [{"code": code, "count": count} for code, count in failures.most_common()],
        "workflow_comparison": sorted(workflow_rows, key=lambda item: (-item["success_rate"], item["workflow"])),
        "slowest_steps": slow_steps,
    }
