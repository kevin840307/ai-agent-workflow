from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from app.runtime_modules.errors import WorkflowError

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
) -> tuple[str, str]:
    """Run an external CLI and stream stdout/stderr separately."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except NotImplementedError:
        return await _run_process_threaded(command, cwd, env=env, on_output=on_output, timeout_sec=timeout_sec)
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

    try:
        await asyncio.wait_for(
            asyncio.gather(
                drain("stdout", proc.stdout, stdout_chunks),
                drain("stderr", proc.stderr, stderr_chunks),
                proc.wait(),
            ),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        raise WorkflowError(f"Agent process timed out after {timeout_sec} seconds: {' '.join(command)}") from exc
    code = proc.returncode
    stdout = "".join(stdout_chunks).strip()
    stderr = "".join(stderr_chunks).strip()
    if code != 0:
        detail = stderr or stdout or "no stdout/stderr"
        raise WorkflowError(f"Agent process failed with exit code {code}: {' '.join(command)}\n{detail}".strip())
    return stdout, stderr


async def _run_process_threaded(
    command: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    on_output: AgentOutputCallback | None = None,
    timeout_sec: int | None = None,
) -> tuple[str, str]:
    """Fallback for event loops that cannot spawn asyncio subprocesses on Windows."""

    def execute() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )

    try:
        proc = await asyncio.to_thread(execute)
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(f"Agent process timed out after {exc.timeout} seconds: {' '.join(command)}") from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if on_output:
        for line in stdout.splitlines():
            await on_output("stdout", line)
        for line in stderr.splitlines():
            await on_output("stderr", line)
    if proc.returncode != 0:
        detail = stderr or stdout or "no stdout/stderr"
        raise WorkflowError(f"Agent process failed with exit code {proc.returncode}: {' '.join(command)}\n{detail}".strip())
    return stdout, stderr
