from __future__ import annotations

from typing import Any, Callable

from app.runtime_modules.errors import WorkflowError

from app.workflow.agents import (
    AgentClient,
    AgentOutputCallback,
    AgentRequest,
    AgentResult,
    GenericCliAdapter,
    OpenCodeCliAdapter,
    QwenAdapter,
    run_process_stream,
)
from .settings import load_settings

AdapterFactory = Callable[[dict[str, Any]], AgentClient]

ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "qwen_cli": QwenAdapter,
    "qwen_serve": QwenAdapter,
    "opencode_cli": OpenCodeCliAdapter,
    "cli": GenericCliAdapter,
    "generic_cli": GenericCliAdapter,
}

PROVIDER_TYPE_ALIASES = {
    "qwen": "qwen_cli",
    "opencode": "opencode_cli",
    "codex": "cli",
    "generic": "cli",
}


class AgentManager:
    """Resolve workflow steps to provider adapters.

    Provider implementations live under ``app.workflow.agents.providers`` so
    adding a new agent does not require editing the workflow engine itself.
    """

    def __init__(self, settings_loader: Callable[[], dict[str, Any]] = load_settings) -> None:
        self.settings_loader = settings_loader

    def _settings(self) -> tuple[str, dict[str, AgentClient]]:
        settings = self.settings_loader()
        agent_settings = settings.get("agents") or {}
        providers = agent_settings.get("providers") or {}
        default_agent = agent_settings.get("default") or "qwen"

        agents: dict[str, AgentClient] = {}
        for name, config in providers.items():
            config = dict(config or {})
            config.setdefault("name", name)
            provider_type = config.get("type") or PROVIDER_TYPE_ALIASES.get(name) or f"{name}_cli"
            factory = ADAPTER_FACTORIES.get(provider_type)
            if factory:
                agents[name] = factory(config)
        agents.setdefault("qwen", QwenAdapter())
        return default_agent, agents

    def available_agent_names(self) -> set[str]:
        _default_agent, agents = self._settings()
        return set(agents)

    def default_agent_name(self) -> str:
        default_agent, _agents = self._settings()
        return default_agent

    def resolve(self, step_config: dict[str, Any] | None = None, *, agent_name: str | None = None) -> AgentClient:
        config = step_config or {}
        default_agent, agents = self._settings()
        selected = agent_name or config.get("agent") or config.get("provider") or default_agent
        if selected not in agents:
            raise WorkflowError(f"Unknown agent: {selected}. Available agents: {', '.join(sorted(agents))}")
        return agents[selected]

    def health(self) -> dict[str, Any]:
        default_agent, agents = self._settings()
        return {
            "default": default_agent,
            "providers": {name: agent.health() for name, agent in agents.items()},
        }


def create_agent_manager(settings: dict[str, Any] | None = None) -> AgentManager:
    if settings is None:
        return AgentManager(load_settings)
    return AgentManager(lambda: settings)


__all__ = [
    "AgentClient",
    "AgentManager",
    "AgentOutputCallback",
    "AgentRequest",
    "AgentResult",
    "ADAPTER_FACTORIES",
    "GenericCliAdapter",
    "OpenCodeCliAdapter",
    "PROVIDER_TYPE_ALIASES",
    "QwenAdapter",
    "create_agent_manager",
    "run_process_stream",
]
