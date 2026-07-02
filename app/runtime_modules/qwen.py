from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.testing.mock_agent import mock_qwen_response
from app.runtime_modules.errors import WorkflowError


class QwenCliClient:
    _CREATED_SESSION_KEYS: set[tuple[str, str]] = set()

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

    def command(
        self,
        qwen_session_id: str | None = None,
        include_prompt_flag: bool = True,
        *,
        session_mode: str | None = None,
        cwd: Path | None = None,
    ) -> list[str]:
        cmd = [self.bin]
        if self.bare:
            cmd.append("--bare")
        mode = session_mode or self._session_mode(qwen_session_id, cwd)
        if self.reuse_session and qwen_session_id:
            if mode == "resume":
                cmd.extend(["--resume", qwen_session_id])
            elif mode == "create":
                cmd.extend(["--session-id", qwen_session_id, "--chat-recording"])
        if self.auth_type:
            cmd.extend(["--auth-type", self.auth_type])
        if include_prompt_flag:
            cmd.append("-p")
        return cmd

    def _session_mode(self, qwen_session_id: str | None, cwd: Path | None = None) -> str | None:
        if not (self.reuse_session and qwen_session_id):
            return None
        key = (str(Path(cwd).expanduser().resolve()) if cwd else "", qwen_session_id)
        return "resume" if key in self._CREATED_SESSION_KEYS else "create"

    def _mark_session_created(self, qwen_session_id: str | None, cwd: Path | None = None) -> None:
        if not (self.reuse_session and qwen_session_id):
            return
        key = (str(Path(cwd).expanduser().resolve()) if cwd else "", qwen_session_id)
        self._CREATED_SESSION_KEYS.add(key)

    @staticmethod
    def forget_session(qwen_session_id: str | None = None, cwd: Path | None = None) -> None:
        if not qwen_session_id:
            return
        if cwd is None:
            QwenCliClient._CREATED_SESSION_KEYS = {item for item in QwenCliClient._CREATED_SESSION_KEYS if item[1] != qwen_session_id}
            return
        key = (str(Path(cwd).expanduser().resolve()), qwen_session_id)
        QwenCliClient._CREATED_SESSION_KEYS.discard(key)

    @staticmethod
    def _is_session_exists_error(message: str) -> bool:
        lowered = message.lower()
        return (
            "session id" in lowered
            and "already exists" in lowered
        ) or "active or archived" in lowered or "delete or unarchive" in lowered

    @staticmethod
    def _is_missing_resume_error(message: str) -> bool:
        lowered = message.lower()
        return any(
            phrase in lowered
            for phrase in [
                "session not found",
                "invalid session",
                "unknown session",
                "could not find session",
                "no session found",
                "cannot resume",
            ]
        )

    @staticmethod
    def _is_busy_session_error(message: str) -> bool:
        lowered = message.lower()
        return "already in use" in lowered or "session is busy" in lowered or "session busy" in lowered

    def run(self, prompt: str, cwd: Path, qwen_session_id: str | None = None, timeout_sec: int | None = None) -> str:
        if self.mock:
            return mock_qwen_response(prompt)
        if shutil.which(self.bin) is None:
            raise WorkflowError(f"Qwen CLI not found: {self.bin}. Set QWEN_MOCK=1 for demo mode.")
        try:
            cmd = self.command(qwen_session_id, include_prompt_flag=False, cwd=cwd)
            proc = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            combined = "\n".join(part for part in [stderr, stdout] if part)
            if qwen_session_id and self._is_session_exists_error(combined):
                self._mark_session_created(qwen_session_id, cwd)
                return self._run_with_mode(prompt, cwd, qwen_session_id, "resume", timeout_sec)
            if qwen_session_id and self._is_missing_resume_error(combined):
                self.forget_session(qwen_session_id, cwd)
                return self._run_with_mode(prompt, cwd, qwen_session_id, "create", timeout_sec)
            if qwen_session_id and self._is_busy_session_error(combined):
                return self.run(prompt, cwd, None, timeout_sec)
            raise WorkflowError(combined or f"Qwen CLI failed with exit code {proc.returncode}.")
        self._mark_session_created(qwen_session_id, cwd)
        return stdout

    def _run_with_mode(self, prompt: str, cwd: Path, qwen_session_id: str, mode: str, timeout_sec: int | None = None) -> str:
        try:
            proc = subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False, session_mode=mode, cwd=cwd),
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        combined = "\n".join(part for part in [stderr, stdout] if part)
        if proc.returncode != 0:
            if qwen_session_id and self._is_busy_session_error(combined):
                return self.run(prompt, cwd, None, timeout_sec)
            raise WorkflowError(combined or f"Qwen CLI failed with exit code {proc.returncode}.")
        self._mark_session_created(qwen_session_id, cwd)
        return stdout

    async def run_stream(
        self,
        prompt: str,
        cwd: Path,
        qwen_session_id: str | None = None,
        timeout_sec: int | None = None,
        on_output=None,
        run_id: str | None = None,
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

        def execute(session_mode: str | None = None) -> subprocess.CompletedProcess:
            return subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False, session_mode=session_mode, cwd=cwd),
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec or self.timeout_sec,
            )

        try:
            proc = await asyncio.to_thread(execute)
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if on_output:
            for line in stdout.splitlines():
                await on_output("stdout", line)
            for line in stderr.splitlines():
                await on_output("stderr", line)

        if proc.returncode != 0:
            combined = "\n".join(part for part in [stderr, stdout] if part)
            if qwen_session_id and self._is_session_exists_error(combined):
                if on_output:
                    await on_output("stderr", "Qwen session id already exists; retrying this step with --resume.")
                self._mark_session_created(qwen_session_id, cwd)
                proc = await asyncio.to_thread(execute, "resume")
                stdout = (proc.stdout or "").strip()
                stderr = (proc.stderr or "").strip()
                combined = "\n".join(part for part in [stderr, stdout] if part)
            elif qwen_session_id and self._is_missing_resume_error(combined):
                if on_output:
                    await on_output("stderr", "Qwen resume session was missing; retrying this step by creating the session id.")
                self.forget_session(qwen_session_id, cwd)
                proc = await asyncio.to_thread(execute, "create")
                stdout = (proc.stdout or "").strip()
                stderr = (proc.stderr or "").strip()
                combined = "\n".join(part for part in [stderr, stdout] if part)

            if proc.returncode != 0:
                if qwen_session_id and self._is_busy_session_error(combined):
                    if on_output:
                        await on_output("stderr", "Qwen session is already in use; retrying this step without a reusable session.")
                    return await self.run_stream(prompt, cwd, None, timeout_sec, on_output, run_id)
                raise WorkflowError(
                    combined
                    or f"Qwen CLI failed with exit code {proc.returncode}, but produced no stdout/stderr."
                )

        if not stdout and stderr:
            raise WorkflowError(stderr)

        self._mark_session_created(qwen_session_id, cwd)
        return stdout
