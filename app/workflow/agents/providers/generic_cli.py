from __future__ import annotations

import os
import shlex
import shutil
from typing import Any

from app.testing.mock_agent import mock_qwen_response
from app.runtime_modules.errors import WorkflowError

from ..base import AgentOutputCallback, AgentRequest, AgentResult, run_process_stream


class GenericCliAdapter:
    """Adapter for any CLI-style coding agent.

    This keeps the workflow engine provider-neutral.  Teams can add entries like
    ``codex`` or ``my_agent`` in data/settings.json without changing Python code.
    Supported prompt modes:
    - stdin: command receives the prompt through stdin.
    - last_arg: prompt is appended as the last command argument.
    - prompt_flag: prompt is passed after a configurable flag, default --prompt.
    """

    name = "cli"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.name = str(config.get("name") or config.get("id") or "cli")
        self.bin = os.environ.get("GENERIC_AGENT_BIN") or str(config.get("bin") or self.name)
        self.args = [str(item) for item in config.get("args") or config.get("extraArgs") or []]
        self.prompt_mode = str(config.get("promptMode") or config.get("prompt_mode") or "stdin")
        self.prompt_flag = str(config.get("promptFlag") or config.get("prompt_flag") or "--prompt")
        self.session_flag = str(config.get("sessionFlag") or config.get("session_flag") or "--session")
        self.model_flag = str(config.get("modelFlag") or config.get("model_flag") or "--model")
        self.model = os.environ.get("GENERIC_AGENT_MODEL") or config.get("model")
        self.timeout_sec = int(config.get("timeoutSec") or config.get("timeout_sec") or os.environ.get("GENERIC_AGENT_TIMEOUT_SEC", "1200"))
        self.reuse_session = bool(config.get("reuseSession", config.get("reuse_session", False)))
        self.mock = bool(config.get("mock", False)) or os.environ.get("GENERIC_AGENT_MOCK", "").lower() in {"1", "true", "yes", "on"}

    def _command(self, prompt: str, session_id: str | None = None, *, include_prompt: bool = True) -> list[str]:
        command = [self.bin, *self.args]
        if self.model:
            command.extend([self.model_flag, str(self.model)])
        if self.reuse_session and session_id:
            command.extend([self.session_flag, session_id])
        if include_prompt:
            if self.prompt_mode == "prompt_flag":
                command.extend([self.prompt_flag, prompt])
            elif self.prompt_mode == "last_arg":
                command.append(prompt)
        return command

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        if self.mock:
            output = mock_qwen_response(request.prompt)
            if on_output:
                for line in output.splitlines():
                    await on_output("stdout", line)
            return AgentResult(output=output, session_id=request.session_id, raw_output=output)
        env = os.environ.copy()
        command = self._command(request.prompt, request.session_id, include_prompt=self.prompt_mode != "stdin")
        stdout, stderr = await run_process_stream(
            command,
            request.cwd,
            env=env,
            on_output=on_output,
            timeout_sec=self.timeout_sec,
        )
        output = stdout or stderr
        return AgentResult(output=output, session_id=request.session_id, raw_output="\n".join(x for x in [stdout, stderr] if x))

    def command_preview(self, request: AgentRequest) -> str:
        if self.prompt_mode == "stdin":
            command = self._command("", request.session_id, include_prompt=False)
            return f"{shlex.join(command)} < prompt.md"
        if self.prompt_mode == "prompt_flag":
            command = self._command("<prompt>", request.session_id, include_prompt=True)
            return shlex.join(command)
        command = self._command("<prompt>", request.session_id, include_prompt=True)
        return shlex.join(command)

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "cli",
            "mock": self.mock,
            "bin": self.bin,
            "exists": self.mock or shutil.which(self.bin) is not None,
            "args": self.args,
            "prompt_mode": self.prompt_mode,
            "reuse_session": self.reuse_session,
            "timeout_sec": self.timeout_sec,
            "model": self.model,
        }
