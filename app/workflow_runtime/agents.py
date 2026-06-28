from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from app.runtime_errors import WorkflowError

from .qwen_serve import QwenCliClient
from .settings import load_settings

AgentOutputCallback = Callable[[str, str], Awaitable[None]]


@dataclass(slots=True)
class AgentRequest:
    run_id: str
    step_key: str
    prompt: str
    cwd: Path
    session_id: str | None = None
    profile: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentResult:
    output: str
    session_id: str | None = None
    raw_output: str | None = None


class AgentClient(Protocol):
    name: str

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        ...

    def command_preview(self, request: AgentRequest) -> str:
        ...

    def health(self) -> dict[str, Any]:
        ...


async def run_process_stream(
    command: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    on_output: AgentOutputCallback | None = None,
) -> tuple[str, str]:
    """Run an external CLI and stream stdout/stderr separately.

    Artifact content should normally come from stdout only.  stderr is still
    streamed to the UI and included in errors when the process fails.
    """
    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def drain(stream_name: str, stream: asyncio.StreamReader | None, chunks: list[str]) -> None:
        if stream is None:
            return
        while True:
            data = await stream.readline()
            if not data:
                break
            text = data.decode(errors="replace")
            chunks.append(text)
            if on_output:
                await on_output(stream_name, text)

    await asyncio.gather(
        drain("stdout", proc.stdout, stdout_chunks),
        drain("stderr", proc.stderr, stderr_chunks),
    )
    code = await proc.wait()
    stdout = "".join(stdout_chunks).strip()
    stderr = "".join(stderr_chunks).strip()
    if code != 0:
        detail = stderr or stdout or "no stdout/stderr"
        raise WorkflowError(f"Agent process failed with exit code {code}: {' '.join(command)}\n{detail}".strip())
    return stdout, stderr


class QwenCliAdapter:
    name = "qwen"

    def __init__(self) -> None:
        # Create the client at adapter construction time.  AgentManager rebuilds
        # adapters from current settings on each resolve/health call, so config
        # changes are picked up without restarting the server.
        self.client = QwenCliClient()

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        output = await self.client.run_stream(
            request.prompt,
            request.cwd,
            request.session_id,
            on_output=on_output,
            run_id=request.run_id,
        )
        return AgentResult(output=output, session_id=request.session_id, raw_output=output)

    def command_preview(self, request: AgentRequest) -> str:
        return " ".join([*self.client.command(request.session_id, include_prompt_flag=False), "<prompt via stdin>"])

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "qwen_cli",
            "mock": self.client.mock,
            "bin": self.client.bin,
            "reuse_session": self.client.reuse_session,
            "bare": self.client.bare,
            "auth_type": self.client.auth_type or None,
            "timeout_sec": self.client.timeout_sec,
            "exists": self.client.mock or shutil.which(self.client.bin) is not None,
        }


class OpenCodeCliAdapter:
    """Adapter for OpenCode or OpenCode-compatible command line agents.

    Supported modes:
    - ``run``:         opencode run <prompt>
    - ``prompt_flag``: opencode -p <prompt>

    Keep the mode configurable because CLI distributions may differ.
    """

    name = "opencode"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.bin = config.get("bin") or "opencode"
        self.mode = config.get("mode") or "run"
        self.config_dir = config.get("configDir") or config.get("config_dir")
        self.extra_args = list(config.get("extraArgs") or config.get("extra_args") or [])

    def _command(self, prompt: str) -> list[str]:
        if self.mode == "prompt_flag":
            return [self.bin, "-p", prompt, *self.extra_args]
        return [self.bin, "run", prompt, *self.extra_args]

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        env = os.environ.copy()
        if self.config_dir:
            env["OPENCODE_CONFIG_DIR"] = str(self.config_dir)
        stdout, stderr = await run_process_stream(self._command(request.prompt), request.cwd, env=env, on_output=on_output)
        output = stdout or stderr
        return AgentResult(output=output, session_id=request.session_id, raw_output="\n".join(x for x in [stdout, stderr] if x))

    def command_preview(self, request: AgentRequest) -> str:
        if self.mode == "prompt_flag":
            return f"{self.bin} -p <prompt>"
        return f"{self.bin} run <prompt>"

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "opencode_cli",
            "bin": self.bin,
            "exists": shutil.which(self.bin) is not None,
            "mode": self.mode,
            "config_dir": self.config_dir,
        }


class AgentManager:
    """Resolve workflow steps to agent adapters.

    This manager is intentionally settings-backed and rebuilds adapters on each
    call.  The existing config API mutates settings at runtime, so caching a
    Qwen/OpenCode client at process startup would make config changes stale.
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
            config = config or {}
            provider_type = config.get("type") or f"{name}_cli"
            if name == "qwen" or provider_type == "qwen_cli":
                agents[name] = QwenCliAdapter()
            elif name == "opencode" or provider_type == "opencode_cli":
                agents[name] = OpenCodeCliAdapter(config)
        agents.setdefault("qwen", QwenCliAdapter())
        return default_agent, agents

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
