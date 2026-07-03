from __future__ import annotations

import os
import shutil
from typing import Any

from app.testing.mock_agent import mock_qwen_response
from app.runtime_modules.errors import WorkflowError
from app.security.workspace_guard import apply_workspace_env

from ..base import AgentOutputCallback, AgentRequest, AgentResult, run_process_stream
from app.workflow_runtime.agent_stream_events import AgentJsonStreamParser


class OpenCodeCliAdapter:
    """Adapter for OpenCode or OpenCode-compatible command line agents."""

    name = "opencode"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.bin = os.environ.get("OPENCODE_BIN") or self._resolve_bin(config.get("bin"))
        self.mode = config.get("mode") or "run"
        self.config_dir = config.get("configDir") or config.get("config_dir")
        self.model = os.environ.get("OPENCODE_MODEL") or config.get("model")
        self.agent = os.environ.get("OPENCODE_AGENT") or config.get("agent")
        self.timeout_sec = int(os.environ.get("OPENCODE_TIMEOUT_SEC") or config.get("timeoutSec") or config.get("timeout_sec") or 1200)
        self.mock = bool(config.get("mock", False)) or os.environ.get("OPENCODE_MOCK", "").lower() in {"1", "true", "yes"}
        env_reuse = os.environ.get("OPENCODE_REUSE_SESSION")
        self.reuse_session = (
            env_reuse.lower() not in {"0", "false", "no", "off"}
            if env_reuse is not None
            else bool(config.get("reuseSession", config.get("reuse_session", True)))
        )
        self.thinking = bool(config.get("thinking", False))
        self.skip_permissions = bool(config.get("dangerouslySkipPermissions", config.get("dangerously_skip_permissions", False)))
        self.extra_args = list(config.get("extraArgs") or config.get("extra_args") or [])

    def _default_bin(self) -> str:
        if os.name == "nt":
            return shutil.which("opencode.cmd") or shutil.which("opencode.exe") or "opencode.cmd"
        return "opencode"

    def _resolve_bin(self, configured: str | None) -> str:
        value = str(configured or "").strip()
        if os.name == "nt" and value.lower() in {"", "opencode"}:
            return self._default_bin()
        return value or self._default_bin()

    def _command(self, prompt: str, session_id: str | None = None) -> list[str]:
        session_args = ["--session", session_id] if self.reuse_session and session_id else []
        option_args: list[str] = []
        if self.model:
            option_args.extend(["--model", str(self.model)])
        if self.agent:
            option_args.extend(["--agent", str(self.agent)])
        if self.thinking:
            option_args.append("--thinking")
        if self.mode == "run":
            option_args.extend(["--format", "json"])
        if self.skip_permissions:
            option_args.append("--dangerously-skip-permissions")
        if self.mode == "prompt_flag":
            return [self.bin, "--prompt", prompt, *session_args, *option_args, *self.extra_args]
        return [self.bin, "run", *session_args, *option_args, prompt, *self.extra_args]

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        if self.mock:
            output = mock_qwen_response(request.prompt)
            if on_output:
                for line in output.splitlines():
                    await on_output("stdout", line)
            return AgentResult(output=output, session_id=request.session_id, raw_output=output)
        env = apply_workspace_env(os.environ, project_path=request.cwd, workspace_path=(request.metadata or {}).get("workspace_path"), run_id=request.run_id)
        if self.config_dir:
            env["OPENCODE_CONFIG_DIR"] = str(self.config_dir)
        try:
            stdout, stderr = await self._run_process(request, env, on_output, request.session_id)
            result_session_id = request.session_id
        except WorkflowError as exc:
            if not self._is_recoverable_session_error(exc) or not request.session_id:
                raise
            if on_output:
                await on_output("stderr", "OpenCode session was not found; retrying once with a fresh agent session.")
            stdout, stderr = await self._run_process(request, env, on_output, None)
            result_session_id = None
        output = stdout or stderr
        return AgentResult(output=output, session_id=result_session_id, raw_output="\n".join(x for x in [stdout, stderr] if x))

    async def _run_process(
        self,
        request: AgentRequest,
        env: dict[str, str],
        on_output: AgentOutputCallback | None,
        session_id: str | None,
    ) -> tuple[str, str]:
        parser = AgentJsonStreamParser()

        async def parse_output(stream: str, text: str) -> None:
            if stream == "stdout":
                for line in text.splitlines() or [text]:
                    for parsed_stream, parsed_text in parser.feed_line(line):
                        if on_output:
                            await on_output(parsed_stream, parsed_text)
                return
            if on_output:
                await on_output(stream, text)

        raw_stdout, stderr = await run_process_stream(
            self._command(request.prompt, session_id),
            request.cwd,
            env=env,
            on_output=parse_output,
            timeout_sec=self.timeout_sec,
        )
        if not parser.final_text() and raw_stdout:
            for line in raw_stdout.splitlines():
                parser.feed_line(line)
        return parser.final_text(raw_stdout), stderr

    @staticmethod
    def _is_recoverable_session_error(exc: WorkflowError) -> bool:
        message = str(exc).lower()
        return any(
            phrase in message
            for phrase in [
                "session not found",
                "invalid session",
                "unknown session",
                "could not find session",
                "no session found",
            ]
        )

    def command_preview(self, request: AgentRequest) -> str:
        if self.mode == "prompt_flag":
            session = " --session <session>" if self.reuse_session and request.session_id else ""
            return f"{self.bin} --prompt <prompt>{session}"
        session = " --session <session>" if self.reuse_session and request.session_id else ""
        return f"{self.bin} run{session} --format json <prompt>"

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "opencode_cli",
            "mock": self.mock,
            "bin": self.bin,
            "exists": self.mock or shutil.which(self.bin) is not None,
            "mode": self.mode,
            "config_dir": self.config_dir,
            "reuse_session": self.reuse_session,
            "timeout_sec": self.timeout_sec,
            "model": self.model,
            "agent": self.agent,
            "thinking": self.thinking,
            "dangerously_skip_permissions": self.skip_permissions,
            "session_flag": "--session",
        }
