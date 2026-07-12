from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from app.agents.process_supervisor import terminate_popen_tree
from app.security.redaction import redact_text


class CommandPolicy(str, Enum):
    TRUSTED = "trusted_command"
    PROJECT = "project_command"
    AGENT_GENERATED = "agent_generated_command"


class CommandPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CommandRequest:
    command: str | Sequence[str]
    cwd: Path
    timeout_seconds: float | None = None
    policy: CommandPolicy = CommandPolicy.PROJECT
    project_root: Path | None = None
    shell: bool | None = None
    env: Mapping[str, str] | None = None
    max_output_chars: int = 200_000


@dataclass(frozen=True)
class CommandResult:
    command: str
    cwd: str
    policy: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    output_truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0

    @property
    def failure_code(self) -> str | None:
        if self.timed_out:
            return "TIMEOUT"
        if self.returncode != 0:
            return "COMMAND_FAILED"
        return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _normalize_request(request: CommandRequest) -> tuple[str | list[str], bool, Path, str]:
    cwd = Path(request.cwd).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        raise CommandPolicyError(f"COMMAND_CWD_INVALID: {cwd}")

    project_root = Path(request.project_root or cwd).expanduser().resolve()
    if request.policy in {CommandPolicy.PROJECT, CommandPolicy.AGENT_GENERATED} and not _is_within(cwd, project_root):
        raise CommandPolicyError(f"COMMAND_CWD_OUTSIDE_PROJECT: cwd={cwd} root={project_root}")

    if isinstance(request.command, str):
        command: str | list[str] = request.command.strip()
        if not command:
            raise CommandPolicyError("COMMAND_EMPTY")
        if request.policy is CommandPolicy.AGENT_GENERATED:
            raise CommandPolicyError("AGENT_GENERATED_COMMAND_REQUIRES_ARGV")
        shell = True if request.shell is None else bool(request.shell)
        display = command
    else:
        command = [str(part) for part in request.command]
        if not command or not command[0].strip():
            raise CommandPolicyError("COMMAND_EMPTY")
        shell = False if request.shell is None else bool(request.shell)
        if request.policy is CommandPolicy.AGENT_GENERATED and shell:
            raise CommandPolicyError("AGENT_GENERATED_COMMAND_FORBIDS_SHELL")
        display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)

    return command, shell, cwd, redact_text(display)


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(value) <= limit:
        return value, False
    head = max(1, limit // 3)
    tail = max(1, limit - head)
    removed = len(value) - head - tail
    marker = f"\n...[COMMAND OUTPUT TRUNCATED: {removed} chars omitted]...\n"
    return value[:head] + marker + value[-tail:], True


def run_command(request: CommandRequest) -> CommandResult:
    command, shell, cwd, display = _normalize_request(request)
    env = os.environ.copy()
    if request.env:
        env.update({str(key): str(value) for key, value in request.env.items()})

    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        shell=shell,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=(os.name != "nt"),
        creationflags=creationflags,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_popen_tree(process, grace_sec=1.5)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()

    duration = round(time.monotonic() - started, 3)
    stdout, stdout_truncated = _truncate(redact_text(stdout or ""), request.max_output_chars)
    stderr, stderr_truncated = _truncate(redact_text(stderr or ""), request.max_output_chars)
    return CommandResult(
        command=display,
        cwd=str(cwd),
        policy=request.policy.value,
        returncode=124 if timed_out else int(process.returncode or 0),
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
        timed_out=timed_out,
        output_truncated=stdout_truncated or stderr_truncated,
    )


async def run_command_async(request: CommandRequest) -> CommandResult:
    return await asyncio.to_thread(run_command, request)


__all__ = [
    "CommandPolicy",
    "CommandPolicyError",
    "CommandRequest",
    "CommandResult",
    "run_command",
    "run_command_async",
]
