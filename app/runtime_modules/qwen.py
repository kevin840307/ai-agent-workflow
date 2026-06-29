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

    def command(self, qwen_session_id: str | None = None, include_prompt_flag: bool = True) -> list[str]:
        cmd = [self.bin]
        if self.bare:
            cmd.append("--bare")
        if self.reuse_session and qwen_session_id:
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
        try:
            proc = subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False),
                input=prompt,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_sec or self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Qwen CLI timed out after {exc.timeout} seconds.") from exc
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            if qwen_session_id and "already in use" in stderr:
                return self.run(prompt, cwd, None, timeout_sec)
            raise WorkflowError(proc.stderr.strip() or f"Qwen CLI failed with exit code {proc.returncode}.")
        return proc.stdout.strip()

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

        def execute() -> subprocess.CompletedProcess:
            return subprocess.run(
                self.command(qwen_session_id, include_prompt_flag=False),
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
            if qwen_session_id and "already in use" in stderr:
                if on_output:
                    await on_output("stderr", "Qwen session is already in use; retrying this step without --session-id.")
                return await self.run_stream(prompt, cwd, None, timeout_sec, on_output, run_id)

            raise WorkflowError(
                stderr
                or stdout
                or f"Qwen CLI failed with exit code {proc.returncode}, but produced no stdout/stderr."
            )

        if not stdout and stderr:
            raise WorkflowError(stderr)

        return stdout
