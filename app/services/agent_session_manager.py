from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.paths import utc_now
from app.workflow_runtime.step_metadata import step_session_role


ROLE_ALIASES = {
    "planning": "planning",
    "planner": "planning",
    "build": "build",
    "execution": "build",
    "validation": "validation",
    "test_repair": "validation",
    "review": "review",
}


@dataclass(slots=True)
class SessionDecision:
    role: str
    agent: str
    session_id: str | None
    fresh: bool
    reason: str


class AgentSessionManager:
    """Single policy point for workflow agent-session roles.

    The manager intentionally keeps provider session creation inside the
    provider adapters. It decides only whether an existing role session may be
    reused and records the result in run state for persistence/diagnostics.
    """

    @staticmethod
    def role_for_step(step: dict[str, Any] | str | None) -> str:
        if isinstance(step, dict):
            return step_session_role(step)
        # A bare key carries no semantics. Callers should pass the step contract.
        return "build"

    def resolve(
        self,
        run: dict[str, Any],
        *,
        step_key: str,
        agent: str,
        fresh: bool = False,
        reason: str | None = None,
    ) -> SessionDecision:
        step = next((item for item in run.get("steps", []) if item.get("key") == step_key), {"key": step_key})
        role = self.role_for_step(step)
        if fresh:
            return SessionDecision(role, agent, None, True, reason or "fresh_session_requested")
        role_sessions = run.get("role_session_ids") or {}
        role_value = role_sessions.get(role) if isinstance(role_sessions, dict) else None
        session_id: str | None = None
        if isinstance(role_value, dict):
            raw = role_value.get(agent)
            session_id = str(raw) if raw else None
        elif isinstance(role_value, str) and role_value:
            session_id = role_value
        if not session_id:
            providers = run.get("agent_session_ids") or {}
            raw = providers.get(agent) if isinstance(providers, dict) else None
            session_id = str(raw) if raw else None
        if not session_id:
            if agent == "qwen":
                session_id = run.get("qwen_session_id")
            else:
                session_id = run.get("agent_session_id")
        return SessionDecision(role, agent, session_id, False, reason or ("role_session" if session_id else "new_session"))

    @staticmethod
    def record(
        run: dict[str, Any],
        *,
        role: str,
        agent: str,
        session_id: str | None,
        status: str = "active",
        recovery_reason: str | None = None,
    ) -> None:
        role = ROLE_ALIASES.get(str(role), str(role))
        role_sessions = run.setdefault("role_session_ids", {})
        role_map = role_sessions.setdefault(role, {})
        if not isinstance(role_map, dict):
            role_map = {}
            role_sessions[role] = role_map
        if session_id:
            role_map[agent] = session_id
            run.setdefault("agent_session_ids", {})[agent] = session_id
            if agent == "qwen":
                run["qwen_session_id"] = session_id
        records = run.setdefault("session_records", [])
        records.append(
            {
                "role": role,
                "agent": agent,
                "session_id": session_id,
                "status": status,
                "recovery_reason": recovery_reason,
                "updated_at": utc_now(),
            }
        )
        if len(records) > 100:
            del records[:-100]

    @staticmethod
    def invalidate(run: dict[str, Any], *, step_key: str, agent: str, reason: str) -> None:
        step = next((item for item in run.get("steps", []) if item.get("key") == step_key), {"key": step_key})
        role = AgentSessionManager.role_for_step(step)
        role_sessions = run.get("role_session_ids") or {}
        value = role_sessions.get(role) if isinstance(role_sessions, dict) else None
        if isinstance(value, dict):
            value.pop(agent, None)
        run.setdefault("session_invalidations", []).append(
            {"role": role, "agent": agent, "reason": reason, "at": utc_now()}
        )
        if len(run["session_invalidations"]) > 50:
            run["session_invalidations"] = run["session_invalidations"][-50:]


__all__ = ["AgentSessionManager", "SessionDecision"]
