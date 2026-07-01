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

STEP_AGENT_OPTION_KEYS = {
    "args",
    "extraArgs",
    "extra_args",
    "model",
    "mode",
    "promptMode",
    "prompt_mode",
    "promptFlag",
    "prompt_flag",
    "reuseSession",
    "reuse_session",
    "sessionFlag",
    "session_flag",
    "skipPermissions",
    "thinking",
    "timeoutSec",
    "timeout_sec",
    "dangerouslySkipPermissions",
    "dangerously_skip_permissions",
    "opencodeAgent",
    "agentProfile",
}


class AgentManager:
    """Resolve workflow steps to provider adapters.

    Provider implementations live under ``app.workflow.agents.providers`` so
    adding a new agent does not require editing the workflow engine itself.
    Step metadata may override provider-safe runtime options such as model,
    thinking, timeout, prompt mode, and extra args; it does not change the
    provider selection except through the step's ``agent`` / ``provider`` field.
    """

    def __init__(self, settings_loader: Callable[[], dict[str, Any]] = load_settings) -> None:
        self.settings_loader = settings_loader

    def _agent_settings(self) -> tuple[str, dict[str, dict[str, Any]]]:
        settings = self.settings_loader()
        agent_settings = settings.get("agents") or {}
        providers = {name: dict(config or {}) for name, config in (agent_settings.get("providers") or {}).items()}
        default_agent = agent_settings.get("default") or "qwen"
        providers.setdefault("qwen", {"type": "qwen_cli", "name": "qwen"})
        return default_agent, providers

    def _provider_type(self, name: str, config: dict[str, Any]) -> str:
        return str(config.get("type") or PROVIDER_TYPE_ALIASES.get(name) or f"{name}_cli")

    def _adapter_for(self, name: str, config: dict[str, Any]) -> AgentClient | None:
        provider_type = self._provider_type(name, config)
        factory = ADAPTER_FACTORIES.get(provider_type)
        if not factory:
            return None
        adapter_config = dict(config)
        adapter_config.setdefault("name", name)
        return factory(adapter_config)

    def _merge_step_options(self, provider_config: dict[str, Any], step_config: dict[str, Any]) -> dict[str, Any]:
        merged = dict(provider_config)
        options = step_config.get("agentOptions") or step_config.get("agent_options") or {}
        if isinstance(options, dict):
            merged.update(options)
        for key in STEP_AGENT_OPTION_KEYS:
            if key in step_config and step_config[key] is not None:
                merged[key] = step_config[key]
        if "opencodeAgent" in merged and "agent" not in merged:
            merged["agent"] = merged["opencodeAgent"]
        if "agentProfile" in merged and "agent" not in merged:
            merged["agent"] = merged["agentProfile"]
        return merged

    def _settings(self) -> tuple[str, dict[str, AgentClient]]:
        default_agent, provider_configs = self._agent_settings()
        agents: dict[str, AgentClient] = {}
        for name, config in provider_configs.items():
            adapter = self._adapter_for(name, config)
            if adapter:
                agents[name] = adapter
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
        default_agent, provider_configs = self._agent_settings()
        selected = agent_name or config.get("agent") or config.get("provider") or default_agent
        provider_config = provider_configs.get(selected)
        if provider_config is None:
            available = sorted(name for name, candidate in provider_configs.items() if self._adapter_for(name, candidate))
            raise WorkflowError(f"Unknown agent: {selected}. Available agents: {', '.join(available)}")
        adapter_config = self._merge_step_options(provider_config, config)
        adapter = self._adapter_for(selected, adapter_config)
        if not adapter:
            available = sorted(name for name, candidate in provider_configs.items() if self._adapter_for(name, candidate))
            raise WorkflowError(f"Unknown agent: {selected}. Available agents: {', '.join(available)}")
        return adapter

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
