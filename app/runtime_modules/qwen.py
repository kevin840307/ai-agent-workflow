from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.testing.mock_agent import apply_mock_agent_file_edits, mock_qwen_response
from app.runtime_modules.errors import WorkflowError
from app.security.workspace_guard import apply_workspace_env
from app.workflow_runtime.agent_stream_events import AgentJsonStreamParser
from app.agents.process_supervisor import (
    ProcessSupervisorOptions,
    run_agent_command_sync,
    run_supervised_process,
    run_supervised_process_sync,
)


_CREATED_SESSION_KEYS: set[str] = set()
_CREATED_SESSION_LOCK = threading.Lock()

_SESSION_EXISTS_MARKERS = (
    "already exists",
    "active or archived",
    "delete or unarchive",
)
_SESSION_MISSING_MARKERS = (
    "session not found",
    "invalid session",
    "unknown session",
    "could not find session",
    "no session found",
    # Qwen Code 0.19.x uses this wording when --resume receives an id
    # that has never been recorded.  It does not contain the contiguous
    # phrase "no session found", so keep the exact diagnostic here.
    "no saved session found",
)
_SESSION_BUSY_MARKERS = (
    "already in use",
    "session is already in use",
    "session is busy",
)


class QwenCliClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.bin = os.environ.get("QWEN_BIN") or self._default_bin()
        self.timeout_sec = int(os.environ.get("QWEN_TIMEOUT_SEC", "1200"))
        self.mock = os.environ.get("QWEN_MOCK", "").lower() in {"1", "true", "yes"}
        env_reuse = os.environ.get("QWEN_REUSE_SESSION")
        self.reuse_session = (
            env_reuse.lower() not in {"0", "false", "no"}
            if env_reuse is not None
            else bool(settings.get("reuse_session", False))
        )
        self.bare = os.environ.get("QWEN_BARE", "0").lower() in {"1", "true", "yes"}
        self.auth_type = (os.environ.get("QWEN_AUTH_TYPE") or settings.get("auth_type") or "").strip()

    def _default_bin(self) -> str:
        if os.name == "nt":
            return shutil.which("qwen.cmd") or shutil.which("qwen.exe") or "qwen.cmd"
        return "qwen"

    def _session_key(self, cwd: Path, qwen_session_id: str) -> str:
        return f"{cwd.expanduser().resolve()}::{qwen_session_id}"

    def _session_mode(self, cwd: Path, qwen_session_id: str | None) -> str | None:
        if not self.reuse_session or not qwen_session_id:
            return None
        key = self._session_key(cwd, qwen_session_id)
        with _CREATED_SESSION_LOCK:
            if key in _CREATED_SESSION_KEYS:
                return "resume"

        # App session ids are persisted across controller restarts, while this
        # process-local registry is not.  Starting unknown ids with --session-id
        # therefore produces a noisy "already exists" error for every existing
        # Qwen conversation after a restart.  Probe with --resume first and fall
        # back to --session-id only when Qwen confirms that no history exists.
        return "resume"

    def _mark_session_created(self, cwd: Path, qwen_session_id: str | None) -> None:
        if not qwen_session_id:
            return
        key = self._session_key(cwd, qwen_session_id)
        with _CREATED_SESSION_LOCK:
            _CREATED_SESSION_KEYS.add(key)

    @staticmethod
    def forget_session(qwen_session_id: str | None = None, cwd: Path | None = None) -> None:
        with _CREATED_SESSION_LOCK:
            if not qwen_session_id:
                _CREATED_SESSION_KEYS.clear()
                return
            suffix = f"::{qwen_session_id}"
            prefix = f"{cwd.expanduser().resolve()}::" if cwd else ""
            for key in list(_CREATED_SESSION_KEYS):
                if key.endswith(suffix) and (not prefix or key.startswith(prefix)):
                    _CREATED_SESSION_KEYS.discard(key)

    def command(
        self,
        qwen_session_id: str | None = None,
        include_prompt_flag: bool = True,
        *,
        cwd: Path | None = None,
        session_mode: str | None = None,
        stream_json: bool = False,
    ) -> list[str]:
        cmd = [self.bin]
        if self.bare:
            cmd.append("--bare")
        if self.reuse_session and qwen_session_id:
            mode = session_mode or self._session_mode(cwd or Path.cwd(), qwen_session_id)
            if mode == "resume":
                cmd.extend(["--resume", qwen_session_id, "--chat-recording"])
            else:
                cmd.extend(["--session-id", qwen_session_id, "--chat-recording"])
        if self.auth_type:
            cmd.extend(["--auth-type", self.auth_type])
        if stream_json:
            cmd.extend(["--output-format", "stream-json", "--include-partial-messages"])
        if include_prompt_flag:
            cmd.append("-p")
        return cmd

    def run(self, prompt: str, cwd: Path, qwen_session_id: str | None = None, timeout_sec: int | None = None) -> str:
        if self.mock:
            output = mock_qwen_response(prompt)
            apply_mock_agent_file_edits(output, cwd)
            return output
        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")
        env = apply_workspace_env(os.environ, project_path=cwd, workspace_path=cwd / ".ai-workflow")
        mode = self._session_mode(cwd, qwen_session_id)
        command = self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=mode)
        try:
            stdout, stderr = run_agent_command_sync(
                command,
                cwd,
                env=env,
                input_text=prompt,
                timeout_sec=timeout_sec or self.timeout_sec,
            )
        except WorkflowError as exc:
            recovered = self._recoverable_retry_args(str(exc), mode, qwen_session_id)
            if recovered:
                retry_id, retry_mode = recovered
                return self._run_with_mode(prompt, cwd, retry_id, retry_mode, timeout_sec, env)
            raise
        self._mark_session_created(cwd, qwen_session_id)
        return stdout.strip()

    def _run_with_mode(self, prompt: str, cwd: Path, qwen_session_id: str | None, mode: str | None, timeout_sec: int | None, env: dict[str, str]) -> str:
        stdout, stderr = run_agent_command_sync(
            self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=mode),
            cwd,
            env=env,
            input_text=prompt,
            timeout_sec=timeout_sec or self.timeout_sec,
        )
        if qwen_session_id:
            self._mark_session_created(cwd, qwen_session_id)
        return (stdout or "").strip()

    async def run_stream(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None = None,
        timeout_sec: int | None = None,
        on_output=None,
        run_id: str | None = None,
        env: dict[str, str] | None = None,
        workspace_path: Path | None = None,
    ) -> str:
        if self.mock:
            output = mock_qwen_response(prompt)
            apply_mock_agent_file_edits(output, cwd)
            if on_output:
                for line in output.splitlines():
                    await on_output("stdout", line)
                    await asyncio.sleep(0.02)
            return output

        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")

        process_env = apply_workspace_env(env or os.environ, project_path=cwd, workspace_path=workspace_path or (cwd / ".ai-workflow"), run_id=run_id)
        mode = self._session_mode(cwd, qwen_session_id)
        proc = await self._execute_stream(prompt, cwd, qwen_session_id, mode, timeout_sec, process_env, run_id=run_id, on_output=on_output)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if proc.returncode != 0:
            recovered = self._recoverable_retry_args(stderr or stdout, mode, qwen_session_id)
            if recovered:
                retry_id, retry_mode = recovered
                if on_output:
                    await on_output("status", self._recovery_message(retry_id, retry_mode))
                retry_proc = await self._execute_stream(prompt, cwd, retry_id, retry_mode, timeout_sec, process_env, run_id=run_id, on_output=on_output)
                stdout = (retry_proc.stdout or "").strip()
                stderr = (retry_proc.stderr or "").strip()
                if retry_proc.returncode != 0:
                    raise WorkflowError(stderr or stdout or f"Qwen CLI failed with exit code {retry_proc.returncode}.")
                if retry_id:
                    self._mark_session_created(cwd, retry_id)
                return stdout
            raise WorkflowError(stderr or stdout or f"Qwen CLI failed with exit code {proc.returncode}, but produced no stdout/stderr.")

        if qwen_session_id:
            self._mark_session_created(cwd, qwen_session_id)
        if not stdout and stderr:
            raise WorkflowError(stderr)
        return stdout

    async def _execute_stream(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None,
        session_mode: str | None,
        timeout_sec: int | None,
        env: dict[str, str],
        *,
        run_id: str | None = None,
        on_output=None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return await self._execute_stream_async(prompt, cwd, qwen_session_id, session_mode, timeout_sec, env, run_id=run_id, on_output=on_output)
        except NotImplementedError:
            return await self._execute_stream_threaded(prompt, cwd, qwen_session_id, session_mode, timeout_sec, env, on_output)

    async def _execute_stream_async(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None,
        session_mode: str | None,
        timeout_sec: int | None,
        env: dict[str, str],
        *,
        run_id: str | None = None,
        on_output=None,
    ) -> subprocess.CompletedProcess[str]:
        command = self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=session_mode, stream_json=True)
        parser = AgentJsonStreamParser()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        async def parse_output(stream: str, text: str) -> None:
            if stream == "stdout":
                stdout_chunks.append(text)
                if on_output:
                    for parsed_stream, parsed_text in parser.feed_line(text):
                        await on_output(parsed_stream, parsed_text)
                return
            stderr_chunks.append(text)
            if on_output and not self._is_recoverable_session_diagnostic(text):
                await on_output("stderr", text)

        try:
            from app.runtime_modules import api as runtime_api

            process_registry = runtime_api.running_processes
        except Exception:
            process_registry = None

        result = await run_supervised_process(
            ProcessSupervisorOptions(
                command=command,
                cwd=cwd,
                env=env,
                input_text=prompt,
                on_output=parse_output,
                timeout_sec=timeout_sec or self.timeout_sec,
                run_id=run_id,
                process_registry=process_registry,
            )
        )
        if not parser.final_text() and result.stdout:
            for line in result.stdout.splitlines():
                parser.feed_line(line)
        return subprocess.CompletedProcess(command, result.returncode, parser.final_text(result.stdout), result.stderr)

    async def _execute_stream_threaded(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None,
        session_mode: str | None,
        timeout_sec: int | None,
        env: dict[str, str],
        on_output=None,
    ) -> subprocess.CompletedProcess[str]:
        command = self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=session_mode, stream_json=True)

        def execute() -> tuple[str, str, int]:
            result = run_supervised_process_sync(
                ProcessSupervisorOptions(
                    command=command,
                    cwd=cwd,
                    env=env,
                    input_text=prompt,
                    timeout_sec=timeout_sec or self.timeout_sec,
                )
            )
            return result.stdout, result.stderr, result.returncode

        stdout, stderr, returncode = await asyncio.to_thread(execute)
        parser = AgentJsonStreamParser()
        if on_output:
            for line in (stdout or "").splitlines():
                for stream, text in parser.feed_line(line):
                    await on_output(stream, text)
            for line in (stderr or "").splitlines():
                if not self._is_recoverable_session_diagnostic(line):
                    await on_output("stderr", line)
        else:
            for line in (stdout or "").splitlines():
                parser.feed_line(line)
        return subprocess.CompletedProcess(command, returncode, parser.final_text(stdout or ""), stderr)

    @staticmethod
    def _recoverable_retry_args(stderr: str, mode: str | None, qwen_session_id: str | None) -> tuple[str | None, str | None] | None:
        lower = (stderr or "").lower()
        if qwen_session_id and any(marker in lower for marker in _SESSION_EXISTS_MARKERS):
            return qwen_session_id, "resume"
        if qwen_session_id and any(marker in lower for marker in _SESSION_MISSING_MARKERS):
            return qwen_session_id, "create"
        if qwen_session_id and any(marker in lower for marker in _SESSION_BUSY_MARKERS):
            return None, None
        return None

    @staticmethod
    def _is_recoverable_session_diagnostic(text: str) -> bool:
        lower = (text or "").lower()
        return any(
            marker in lower
            for marker in (*_SESSION_EXISTS_MARKERS, *_SESSION_MISSING_MARKERS, *_SESSION_BUSY_MARKERS)
        )

    @staticmethod
    def _recovery_message(qwen_session_id: str | None, mode: str | None) -> str:
        if qwen_session_id is None:
            return "Qwen session is currently busy; continuing without reused session context."
        if mode == "create":
            return "No existing Qwen session history was found; creating the session now."
        return "Existing Qwen session detected; resuming it now."
