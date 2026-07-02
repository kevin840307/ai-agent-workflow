from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.testing.mock_agent import mock_qwen_response
from app.runtime_modules.errors import WorkflowError
from app.security.workspace_guard import apply_workspace_env


_CREATED_SESSION_KEYS: set[str] = set()
_CREATED_SESSION_LOCK = threading.Lock()


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
            return "resume" if key in _CREATED_SESSION_KEYS else "create"

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
    ) -> list[str]:
        cmd = [self.bin]
        if self.bare:
            cmd.append("--bare")
        if self.reuse_session and qwen_session_id:
            mode = session_mode or (self._session_mode(cwd or Path.cwd(), qwen_session_id) if cwd else "create")
            if mode == "resume":
                cmd.extend(["--resume", qwen_session_id, "--chat-recording"])
            else:
                cmd.extend(["--session-id", qwen_session_id, "--chat-recording"])
        if self.auth_type:
            cmd.extend(["--auth-type", self.auth_type])
        if include_prompt_flag:
            cmd.append("-p")
        return cmd

    def run(self, prompt: str, cwd: Path, qwen_session_id: str | None = None, timeout_sec: int | None = None) -> str:
        if self.mock:
            return mock_qwen_response(prompt)
        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")
        env = apply_workspace_env(os.environ, project_path=cwd, workspace_path=cwd / ".ai-workflow")
        mode = self._session_mode(cwd, qwen_session_id)
        try:
            proc = subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=mode),
                input=prompt,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            recovered = self._recoverable_retry_args(stderr, mode, qwen_session_id)
            if recovered:
                retry_id, retry_mode = recovered
                return self._run_with_mode(prompt, cwd, retry_id, retry_mode, timeout_sec, env)
            raise WorkflowError(proc.stderr.strip() or f"Qwen CLI failed with exit code {proc.returncode}.")
        self._mark_session_created(cwd, qwen_session_id)
        return proc.stdout.strip()

    def _run_with_mode(self, prompt: str, cwd: Path, qwen_session_id: str | None, mode: str | None, timeout_sec: int | None, env: dict[str, str]) -> str:
        proc = subprocess.run(
            self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=mode),
            input=prompt,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec or self.timeout_sec,
        )
        if proc.returncode != 0:
            raise WorkflowError(proc.stderr.strip() or proc.stdout.strip() or f"Qwen CLI failed with exit code {proc.returncode}.")
        if qwen_session_id:
            self._mark_session_created(cwd, qwen_session_id)
        return (proc.stdout or "").strip()

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
            if on_output:
                for line in output.splitlines():
                    await on_output("stdout", line)
                    await asyncio.sleep(0.02)
            return output

        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")

        process_env = apply_workspace_env(env or os.environ, project_path=cwd, workspace_path=workspace_path or (cwd / ".ai-workflow"), run_id=run_id)
        mode = self._session_mode(cwd, qwen_session_id)
        proc = await self._execute_stream(prompt, cwd, qwen_session_id, mode, timeout_sec, process_env)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if on_output:
            for line in stdout.splitlines():
                await on_output("stdout", line)
            for line in stderr.splitlines():
                await on_output("stderr", line)

        if proc.returncode != 0:
            recovered = self._recoverable_retry_args(stderr or stdout, mode, qwen_session_id)
            if recovered:
                retry_id, retry_mode = recovered
                if on_output:
                    await on_output("stderr", f"Qwen session recovered; retrying with {'no session' if retry_id is None else retry_mode} mode.")
                retry_proc = await self._execute_stream(prompt, cwd, retry_id, retry_mode, timeout_sec, process_env)
                stdout = (retry_proc.stdout or "").strip()
                stderr = (retry_proc.stderr or "").strip()
                if on_output:
                    for line in stdout.splitlines():
                        await on_output("stdout", line)
                    for line in stderr.splitlines():
                        await on_output("stderr", line)
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
    ) -> subprocess.CompletedProcess[str]:
        def execute() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd, session_mode=session_mode),
                input=prompt,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec or self.timeout_sec,
            )

        try:
            return await asyncio.to_thread(execute)
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc

    @staticmethod
    def _recoverable_retry_args(stderr: str, mode: str | None, qwen_session_id: str | None) -> tuple[str | None, str | None] | None:
        lower = (stderr or "").lower()
        if qwen_session_id and any(marker in lower for marker in ["already exists", "active or archived", "delete or unarchive"]):
            return qwen_session_id, "resume"
        if qwen_session_id and any(marker in lower for marker in ["session not found", "invalid session", "unknown session", "could not find session", "no session found"]):
            return qwen_session_id, "create"
        if qwen_session_id and any(marker in lower for marker in ["already in use", "session is already in use", "busy"]):
            return None, None
        return None
