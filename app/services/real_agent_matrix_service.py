from __future__ import annotations

from itertools import product
from typing import Any

from app.services import workflow_case_service

SUPPORTED_AGENTS = ["qwen", "opencode"]
SUPPORTED_WORKFLOWS = ["general-auto-development", "adaptive-auto-workflow", "regression-test-case-generation"]


def _case_ids(cases: list[str] | None) -> list[str]:
    if cases:
        return cases
    available_payload = workflow_case_service.list_cases()
    available = available_payload.get("cases", []) if isinstance(available_payload, dict) else available_payload
    discovered = [item.get("id") for item in available if item.get("id")]
    # Prefer stable tiny cases first; callers can pass explicit large cases.
    preferred = [item for item in ["sort", "config-loader", "readme", *discovered] if item]
    return list(dict.fromkeys(preferred))[:4]


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
    mode = (mode or "plan").strip().lower()
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
        if mode in {"dry-run", "dry_run"}:
            command.append("--dry-run")
        elif mode in {"self-prompt", "self_prompt", "self-prompt-test"}:
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
            }
        )
    return {
        "schema": "aiwf.real-agent-matrix.v2",
        "mode": mode,
        "agents": agents,
        "workflows": workflows,
        "cases": case_ids,
        "rows": rows,
        "count": len(rows),
        "summary": {
            "planned": len(rows),
            "real_execution_requires_local_agent_cli": True,
            "safe_modes": ["plan", "dry-run", "self-prompt-test"],
        },
    }


__all__ = ["SUPPORTED_AGENTS", "SUPPORTED_WORKFLOWS", "build_real_agent_matrix"]
