from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.persistence.repositories import store as store_repository
from app.runtime_modules import api as runtime
from app.services.setup_service import setup_status
from app.workflow_runtime.benchmark import summarize_runs
from app.workflow_runtime.complexity import classify_workflow_complexity
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.repair_policy import policy_for_failure
from app.workflow_runtime.risk_engine import assess_risk
from app.workflow_runtime.model_capabilities import resolve_model_capability
from app.workflow_runtime.validators import detect_validator_plans

_TERMINAL = {"done", "failed", "cancelled"}


def _seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        return max(0.0, (right - left).total_seconds())
    except (TypeError, ValueError):
        return None


def _workflow_for(profile: str, requested_workflow: str | None = None) -> tuple[str, str]:
    """Select from explicit caller choice or structural complexity only."""
    if requested_workflow:
        return str(requested_workflow), "使用呼叫端明確指定的 Workflow。"
    if profile == "complex":
        return "adaptive-auto-workflow", "專案結構指標較大，使用動態拆解 Workflow。"
    return "general-auto-development", "使用固定開發 SOP 以提高可預測性。"


def _profile_for(complexity: str) -> tuple[str, str]:
    if complexity == "complex":
        return "strong", "high"
    if complexity == "standard":
        return "normal", "high"
    return "small", "medium"


def _historical_agent_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        agent = str(run.get("agent") or "default")
        if run.get("status") in _TERMINAL:
            groups[agent].append(run)
    rows: list[dict[str, Any]] = []
    for agent, items in groups.items():
        durations = [value for item in items if (value := _seconds(item.get("started_at"), item.get("ended_at"))) is not None]
        done = sum(item.get("status") == "done" for item in items)
        rows.append({
            "agent": agent,
            "runs": len(items),
            "success_rate": round(done * 100 / len(items), 1) if items else 0.0,
            "avg_duration_sec": round(sum(durations) / len(durations), 1) if durations else None,
        })
    return sorted(rows, key=lambda row: (-row["success_rate"], row["avg_duration_sec"] or 10**9, row["agent"]))


def _estimate(profile: str, historical: list[dict[str, Any]], workflow_id: str) -> dict[str, Any]:
    defaults = {
        "tiny": (1, 2, 120, 360, "low", 12_000),
        "standard": (2, 5, 300, 1200, "medium", 35_000),
        "complex": (3, 10, 900, 3600, "high", 80_000),
    }
    task_min, task_max, duration_min, duration_max, cost, prompt_chars = defaults.get(profile, defaults["standard"])
    samples = [
        value
        for run in historical
        if run.get("workflow_id") == workflow_id and run.get("status") == "done"
        if (value := _seconds(run.get("started_at"), run.get("ended_at"))) is not None
    ]
    if samples:
        average = sum(samples) / len(samples)
        duration_min = max(30, int(average * 0.65))
        duration_max = max(duration_min + 30, int(average * 1.6))
    return {
        "task_range": [task_min, task_max],
        "duration_sec_range": [duration_min, duration_max],
        "local_compute_cost": cost,
        "prompt_budget_chars": prompt_chars,
        "historical_samples": len(samples),
    }


def _repair_history(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: Counter[str] = Counter()
    for run in runs:
        if run.get("status") == "failed" or run.get("error"):
            failure = classify_failure(run.get("error"), error_code=run.get("error_code"))
            failures[str(failure.get("code") or "UNKNOWN")] += 1
        for step in run.get("steps") or []:
            if step.get("error"):
                failure = classify_failure(step.get("error"), step_key=step.get("key"), error_code=step.get("error_code"))
                failures[str(failure.get("code") or "UNKNOWN")] += 1
    result = []
    for code, count in failures.most_common(5):
        policy = policy_for_failure(error_code=code)
        result.append({
            "code": code,
            "count": count,
            "strategy": policy.get("prompt_mode"),
            "recommended_action": (policy.get("failure") or {}).get("recommended_action") or policy.get("repair_instruction"),
        })
    return result


async def recommend_execution(
    requirement: str,
    *,
    project_path: str | None = None,
    workflow_id: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    requirement = (requirement or "").strip()
    if not requirement:
        return {"schema": "aiwf.execution-recommendation.v1", "ready": False, "reason": "requirement is empty"}
    try:
        project = runtime.resolve_project_path(project_path or str(runtime.ROOT))
    except Exception:
        project = Path(project_path or runtime.ROOT).expanduser()
    complexity = classify_workflow_complexity(requirement, project)
    recommended_workflow, workflow_reason = _workflow_for(complexity["profile"], workflow_id)
    selected_workflow = recommended_workflow
    run_profile, thinking_level = _profile_for(complexity["profile"])

    data = await store_repository.read()
    historical = list(data.get("runs") or [])[:1000]
    setup = await setup_status(str(project))
    agents = setup.get("agents") or {}
    historical_agents = _historical_agent_rows(historical)
    ready_agents = [name for name in ("qwen", "opencode") if (agents.get(name) or {}).get("ready")]
    historical_ready = [row["agent"] for row in historical_agents if row["agent"] in ready_agents]
    selected_agent = agent or (historical_ready[0] if historical_ready else (ready_agents[0] if ready_agents else "qwen"))

    benchmark = summarize_runs(historical)
    successful_templates = [
        {"workflow_id": wid, **stats}
        for wid, stats in benchmark.get("workflows", {}).items()
        if stats.get("runs") and stats.get("pass_rate", 0) > 0
    ]
    successful_templates.sort(key=lambda row: (-row.get("pass_rate", 0), row.get("average_retry", 0), row["workflow_id"]))
    estimate = _estimate(complexity["profile"], historical, selected_workflow)
    risk = assess_risk(requirement, project_path=project, estimated_file_count=estimate["task_range"][1] * 3)
    capability = resolve_model_capability(run_profile, context_window=(setup.get("model") or {}).get("context_window"))
    validator_plans = detect_validator_plans(project) if project.exists() else []
    confidence = 0.92 if workflow_id else (0.85 if historical else 0.72)
    return {
        "schema": "aiwf.execution-recommendation.v1",
        "ready": True,
        "requirement_summary": requirement[:240],
        "complexity": complexity,
        "recommendation": {
            "workflow_id": selected_workflow,
            "workflow_reason": workflow_reason,
            "agent": selected_agent,
            "run_profile": run_profile,
            "thinking_level": thinking_level,
            "confidence": confidence,
        },
        "estimate": estimate,
        "agent_comparison": historical_agents,
        "successful_templates": successful_templates[:5],
        "historical_repair_strategies": _repair_history(historical),
        "environment_ready": bool(setup.get("ready")),
        "environment_recommendations": setup.get("recommendations") or [],
        "risk": risk,
        "model_capability": capability,
        "validator_plans": validator_plans,
    }


__all__ = ["recommend_execution"]
