from __future__ import annotations

from typing import Any

from app.persistence.repositories import store as store_repository
from app.runtime_modules import api as runtime


DEFAULT_SESSION_AGENTS = ("qwen", "opencode")


def default_agent_session_ids(session_id: str, base_session_id: str | None = None) -> dict[str, str]:
    shared_session_id = base_session_id or session_id
    return {agent_name: shared_session_id for agent_name in DEFAULT_SESSION_AGENTS}


def get_agent_session_id(session: dict[str, Any], agent_name: str, fallback_session_id: str) -> str | None:
    agent_sessions = session.get("agent_session_ids")
    if isinstance(agent_sessions, dict) and agent_name in agent_sessions:
        return agent_sessions.get(agent_name)
    if agent_name == "qwen":
        return session.get("qwen_session_id") or fallback_session_id
    return fallback_session_id


async def update_agent_session_id(session_id: str, agent_name: str, agent_session_id: str | None) -> None:
    def update(data: dict) -> None:
        target = next((item for item in data["sessions"] if item["id"] == session_id), None)
        if not target:
            return None
        target.setdefault("agent_session_ids", default_agent_session_ids(session_id, target.get("qwen_session_id")))
        target["agent_session_ids"][agent_name] = agent_session_id
        if agent_name == "qwen" and agent_session_id:
            target["qwen_session_id"] = agent_session_id
        target["updated_at"] = runtime.utc_now()
        return None

    await store_repository.mutate(update)
