from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, MutableMapping

from app.runtime_modules.errors import WorkflowError

AgentOutputCallback = Callable[[str, str], Awaitable[None]]


@dataclass(slots=True)
class SupervisedProcessResult:
    command: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(slots=True)
class ProcessSupervisorOptions:
    command: list[str]
    cwd: Path
    env: Mapping[str, str] | None = None
    input_text: str | None = None
    on_output: AgentOutputCallback | None = None
    timeout_sec: int | None = None
    run_id: str | None = None
    process_registry: MutableMapping[str, asyncio.subprocess.Process] | None = None


def normalize_cwd(cwd: Path | str) -> Path:
    resolved = Path(cwd).expanduser().resolve()
    if not resolved.exists():
        raise WorkflowError(f"Agent working directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise WorkflowError(f"Agent working directory is not a directory: {resolved}")
    return resolved


def _creation_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


async def _terminate_process_tree(proc: asyncio.subprocess.Process, *, grace_sec: float = 5.0) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        with contextlib_suppress_process_errors():
            proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_sec)
        return
    except asyncio.TimeoutError:
        pass
    with contextlib_suppress_process_errors():
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib_suppress_process_errors():
        await proc.wait()


class contextlib_suppress_process_errors:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type in {ProcessLookupError, RuntimeError, OSError}


async def run_supervised_process(options: ProcessSupervisorOptions) -> SupervisedProcessResult:
    """Run an agent CLI with a normalized cwd, streaming, timeout, and registry support."""
    command = [str(part) for part in options.command]
    if not command:
        raise WorkflowError("Agent command is empty.")
    cwd = normalize_cwd(options.cwd)
    env = dict(options.env or os.environ)
    stdin_mode = asyncio.subprocess.PIPE if options.input_text is not None else None
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=env,
            stdin=stdin_mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_creation_kwargs(),
        )
    except NotImplementedError:
        return await _run_supervised_threaded(options, cwd)
    except FileNotFoundError as exc:
        raise WorkflowError(f"Agent CLI not found: {command[0]}. Set the matching *_MOCK=1 env var for demo mode.") from exc

    if options.run_id and options.process_registry is not None:
        options.process_registry[options.run_id] = proc
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def write_stdin() -> None:
        if options.input_text is None or proc.stdin is None:
            return
        proc.stdin.write(options.input_text.encode("utf-8", errors="replace"))
        await proc.stdin.drain()
        proc.stdin.close()

    async def drain(stream_name: str, stream: asyncio.StreamReader | None, chunks: list[str]) -> None:
        if stream is None:
            return
        while True:
            data = await stream.readline()
            if not data:
                break
            text = data.decode(errors="replace")
            chunks.append(text)
            if options.on_output:
                await options.on_output(stream_name, text)

    try:
        await write_stdin()
        await asyncio.wait_for(
            asyncio.gather(
                drain("stdout", proc.stdout, stdout_chunks),
                drain("stderr", proc.stderr, stderr_chunks),
                proc.wait(),
            ),
            timeout=options.timeout_sec,
        )
    except asyncio.TimeoutError as exc:
        await _terminate_process_tree(proc)
        raise WorkflowError(f"Agent process timed out after {options.timeout_sec} seconds: {' '.join(command)}") from exc
    finally:
        if options.run_id and options.process_registry is not None and options.process_registry.get(options.run_id) is proc:
            options.process_registry.pop(options.run_id, None)

    stdout = "".join(stdout_chunks).strip()
    stderr = "".join(stderr_chunks).strip()
    return SupervisedProcessResult(command=command, cwd=cwd, returncode=proc.returncode or 0, stdout=stdout, stderr=stderr)


async def _run_supervised_threaded(options: ProcessSupervisorOptions, cwd: Path) -> SupervisedProcessResult:
    command = [str(part) for part in options.command]

    def execute() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            input=options.input_text,
            cwd=str(cwd),
            env=dict(options.env or os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=options.timeout_sec,
        )

    try:
        proc = await asyncio.to_thread(execute)
    except FileNotFoundError as exc:
        raise WorkflowError(f"Agent CLI not found: {command[0]}. Set the matching *_MOCK=1 env var for demo mode.") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(f"Agent process timed out after {exc.timeout} seconds: {' '.join(command)}") from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if options.on_output:
        for line in stdout.splitlines():
            await options.on_output("stdout", line)
        for line in stderr.splitlines():
            await options.on_output("stderr", line)
    return SupervisedProcessResult(command=command, cwd=cwd, returncode=proc.returncode, stdout=stdout, stderr=stderr)


async def run_agent_command(
    command: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    on_output: AgentOutputCallback | None = None,
    timeout_sec: int | None = None,
    run_id: str | None = None,
    process_registry: MutableMapping[str, asyncio.subprocess.Process] | None = None,
) -> tuple[str, str]:
    effective_env = env or None
    effective_run_id = run_id or (effective_env or {}).get("AI_WORKFLOW_RUN_ID")
    effective_registry = process_registry
    if effective_run_id and effective_registry is None:
        try:
            from app.runtime_modules import api as runtime_api

            effective_registry = runtime_api.running_processes
        except Exception:
            effective_registry = None
    result = await run_supervised_process(
        ProcessSupervisorOptions(
            command=command,
            cwd=cwd,
            env=effective_env,
            input_text=input_text,
            on_output=on_output,
            timeout_sec=timeout_sec,
            run_id=effective_run_id,
            process_registry=effective_registry,
        )
    )
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "no stdout/stderr"
        raise WorkflowError(f"Agent process failed with exit code {result.returncode}: {' '.join(result.command)}\n{detail}".strip())
    return result.stdout, result.stderr


def run_supervised_process_sync(options: ProcessSupervisorOptions) -> SupervisedProcessResult:
    """Synchronous companion used by legacy/manual code paths.

    Keep cwd validation, input handling, timeout wording, and return payload
    identical to the async supervisor so every real-agent execution path has one
    safety boundary.
    """
    command = [str(part) for part in options.command]
    if not command:
        raise WorkflowError("Agent command is empty.")
    cwd = normalize_cwd(options.cwd)
    try:
        proc = subprocess.run(
            command,
            input=options.input_text,
            cwd=str(cwd),
            env=dict(options.env or os.environ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=options.timeout_sec,
        )
    except FileNotFoundError as exc:
        raise WorkflowError(f"Agent CLI not found: {command[0]}. Set the matching *_MOCK=1 env var for demo mode.") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(f"Agent process timed out after {exc.timeout} seconds: {' '.join(command)}") from exc
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    return SupervisedProcessResult(command=command, cwd=cwd, returncode=proc.returncode, stdout=stdout, stderr=stderr)


def run_agent_command_sync(
    command: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout_sec: int | None = None,
) -> tuple[str, str]:
    result = run_supervised_process_sync(
        ProcessSupervisorOptions(
            command=command,
            cwd=cwd,
            env=env,
            input_text=input_text,
            timeout_sec=timeout_sec,
        )
    )
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "no stdout/stderr"
        raise WorkflowError(f"Agent process failed with exit code {result.returncode}: {' '.join(result.command)}\n{detail}".strip())
    return result.stdout, result.stderr


__all__ = [
    "ProcessSupervisorOptions",
    "SupervisedProcessResult",
    "normalize_cwd",
    "run_agent_command",
    "run_agent_command_sync",
    "run_supervised_process",
    "run_supervised_process_sync",
]
