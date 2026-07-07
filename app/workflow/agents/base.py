from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

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
    timeout_sec: int | None = None,
    run_id: str | None = None,
    process_registry: dict[str, Any] | None = None,
    input_text: str | None = None,
) -> tuple[str, str]:
    """Run an external CLI through the shared process supervisor."""
    from app.agents.process_supervisor import run_agent_command

    if run_id and process_registry is None:
        try:
            from app.runtime_modules import api as runtime_api

            process_registry = runtime_api.running_processes
        except Exception:
            process_registry = None
    return await run_agent_command(
        command,
        cwd,
        env=env,
        input_text=input_text,
        on_output=on_output,
        timeout_sec=timeout_sec,
        run_id=run_id,
        process_registry=process_registry,
    )
