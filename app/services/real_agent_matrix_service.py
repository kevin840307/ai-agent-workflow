from __future__ import annotations

from itertools import product
from typing import Any

SUPPORTED_AGENTS = ["qwen", "opencode"]
SUPPORTED_WORKFLOWS = ["general-auto-development", "adaptive-auto-workflow", "security-scan"]

# Small, deterministic cases that can be executed safely against a real local
# agent. Failure injection and language/toolchain cases live in the benchmark
# catalog because they require controlled infrastructure rather than prompt
# wording alone.
DEFAULT_EXECUTABLE_CASES = [
    "sort",
    "config-loader",
    "readme",
    "code-with-validation",
    "simple-code-generation",
]

CERTIFICATION_SCENARIOS = [
    {"id": "CERT-001", "title": "Single-file addition", "layer": "real-agent", "executable_case": "sort"},
    {"id": "CERT-002", "title": "Existing bug repair", "layer": "benchmark", "benchmark_id": "BENCH-003"},
    {"id": "CERT-003", "title": "Multi-file feature", "layer": "benchmark", "benchmark_id": "BENCH-002"},
    {"id": "CERT-004", "title": "Test-only update", "layer": "real-agent", "executable_case": "code-with-validation"},
    {"id": "CERT-005", "title": "Validation failure repair", "layer": "benchmark", "benchmark_id": "BENCH-011"},
    {"id": "CERT-006", "title": "No-file-change recovery", "layer": "benchmark", "benchmark_id": "BENCH-012"},
    {"id": "CERT-007", "title": "Transient agent interruption", "layer": "benchmark", "benchmark_id": "BENCH-005"},
    {"id": "CERT-008", "title": "Lost session recovery", "layer": "benchmark", "benchmark_id": "BENCH-006"},
    {"id": "CERT-009", "title": "Context handoff", "layer": "benchmark", "benchmark_id": "BENCH-007"},
    {"id": "CERT-010", "title": "Large legacy project local change", "layer": "benchmark", "benchmark_id": "BENCH-013"},
    {"id": "CERT-011", "title": "Multi-language validation", "layer": "benchmark", "benchmark_id": "BENCH-014"},
    {"id": "CERT-012", "title": "Protected-file and scope guard", "layer": "benchmark", "benchmark_id": "BENCH-010"},
]

QUALITY_THRESHOLDS = {
    "success_after_repair_min": 0.90,
    "manual_intervention_max": 0.10,
    "scope_violation_max": 0,
    "external_validation_pass_rate_min": 0.95,
}


def _case_ids(cases: list[str] | None) -> list[str]:
    return list(dict.fromkeys(cases or DEFAULT_EXECUTABLE_CASES))


def summarize_real_agent_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [
        row
        for row in rows
        if row.get("status") in {"passed", "failed"}
        and isinstance(row.get("result"), dict)
        and row["result"].get("schema") == "aiwf.real-agent-acceptance-cell.v1"
    ]
    if not executed:
        return {
            "executed": 0,
            "success_at_1": None,
            "success_after_repair": None,
            "external_validation_pass_rate": None,
            "no_file_change_rate": None,
            "manual_intervention_rate": None,
            "scope_violation_count": 0,
            "average_retries": None,
            "average_duration_seconds": None,
            "context_handoff_count": 0,
            "fresh_session_count": 0,
            "certified": None,
        }

    passed = 0
    success_at_1 = 0
    validation_passed = 0
    no_file_change = 0
    manual = 0
    scope_violations = 0
    retries: list[int] = []
    durations: list[float] = []
    handoffs = 0
    fresh_sessions = 0

    for row in executed:
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        acceptance = result.get("acceptance") if isinstance(result.get("acceptance"), dict) else {}
        retry_total = int(acceptance.get("retry_total") or 0)
        recovery = acceptance.get("recovery_counters") if isinstance(acceptance.get("recovery_counters"), dict) else {}
        status_passed = row.get("status") == "passed"
        passed += int(status_passed)
        success_at_1 += int(status_passed and retry_total == 0)
        validation_passed += int(bool(acceptance.get("external_validation_passed")))
        no_file_change += int(int(recovery.get("failure:NO_FILE_CHANGE") or recovery.get("class:NO_FILE_CHANGE") or 0) > 0)
        manual += int(bool(acceptance.get("manual_intervention")))
        scope_violations += int(acceptance.get("scope_violation_count") or 0)
        handoffs += int(acceptance.get("context_handoff_count") or 0)
        fresh_sessions += int(acceptance.get("fresh_session_count") or max(0, int(acceptance.get("session_count") or 1) - 1))
        retries.append(retry_total)
        durations.append(float(row.get("duration_seconds") or 0))

    total = len(executed)
    success_after_repair_rate = passed / total
    manual_rate = manual / total
    validation_rate = validation_passed / total
    certified = (
        success_after_repair_rate >= QUALITY_THRESHOLDS["success_after_repair_min"]
        and manual_rate <= QUALITY_THRESHOLDS["manual_intervention_max"]
        and scope_violations <= QUALITY_THRESHOLDS["scope_violation_max"]
        and validation_rate >= QUALITY_THRESHOLDS["external_validation_pass_rate_min"]
    )
    return {
        "executed": total,
        "success_at_1": round(success_at_1 / total, 4),
        "success_after_repair": round(success_after_repair_rate, 4),
        "external_validation_pass_rate": round(validation_rate, 4),
        "no_file_change_rate": round(no_file_change / total, 4),
        "manual_intervention_rate": round(manual_rate, 4),
        "scope_violation_count": scope_violations,
        "average_retries": round(sum(retries) / total, 3),
        "average_duration_seconds": round(sum(durations) / total, 3),
        "context_handoff_count": handoffs,
        "fresh_session_count": fresh_sessions,
        "certified": certified,
    }


def build_real_agent_matrix(
    *,
    agents: list[str] | None = None,
    workflows: list[str] | None = None,
    cases: list[str] | None = None,
    mode: str | None = None,
    output_root: str | None = None,
) -> dict[str, Any]:
    agents = agents or SUPPORTED_AGENTS
    workflows = workflows or ["general-auto-development", "adaptive-auto-workflow"]
    case_ids = _case_ids(cases)
    mode = (mode or "plan").strip().lower().replace("_", "-")
    output_root = output_root or "reports/real-agent-matrix"
    rows = []
    for agent, workflow, case_id in product(agents, workflows, case_ids):
        safe = f"{agent}-{workflow}-{case_id}".replace("/", "-")
        command = [
            "python",
            "scripts/run_real_agent_smoke.py",
            "--agent",
            agent,
            "--workflow",
            workflow,
            "--case",
            case_id,
            "--output",
            f"{output_root}/{safe}",
        ]
        if mode == "dry-run":
            command.append("--dry-run")
        elif mode in {"self-prompt", "self-prompt-test"}:
            command.append("--self-prompt-test")
        rows.append(
            {
                "agent": agent,
                "workflow_id": workflow,
                "case_id": case_id,
                "mode": mode,
                "status": "planned",
                "output": f"{output_root}/{safe}",
                "command": " ".join(command),
                "argv": command,
                "acceptance": {
                    "run_status": "done",
                    "external_validation": "passed",
                    "project_files_generated_by_agent": True,
                    "workspace_isolation": True,
                    "scope_violation_count": 0,
                },
            }
        )
    return {
        "schema": "aiwf.real-agent-matrix.v4",
        "mode": mode,
        "agents": agents,
        "workflows": workflows,
        "cases": case_ids,
        "rows": rows,
        "count": len(rows),
        "certification": {
            "scenarios": CERTIFICATION_SCENARIOS,
            "scenario_count": len(CERTIFICATION_SCENARIOS),
            "quality_thresholds": QUALITY_THRESHOLDS,
            "metrics": summarize_real_agent_rows(rows),
        },
        "summary": {
            "planned": len(rows),
            "real_execution_requires_local_agent_cli": True,
            "safe_modes": ["plan", "dry-run", "self-prompt-test"],
            "execution_modes": ["real"],
            "entrypoints": ["web-api", "python-cli", "/wf", "/wstep"],
            "shared_core": ["AgentManager", "AgentExecutionService", "AgentSessionManager", "WorkflowExecutor"],
        },
    }


__all__ = [
    "CERTIFICATION_SCENARIOS",
    "DEFAULT_EXECUTABLE_CASES",
    "QUALITY_THRESHOLDS",
    "SUPPORTED_AGENTS",
    "SUPPORTED_WORKFLOWS",
    "build_real_agent_matrix",
    "summarize_real_agent_rows",
]
