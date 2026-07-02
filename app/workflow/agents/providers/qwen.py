from __future__ import annotations

import os
import shutil
from typing import Any

from app.workflow_runtime.qwen_serve import QwenCliClient, run_prompt_via_serve

from ..base import AgentOutputCallback, AgentRequest, AgentResult


class QwenAdapter:
    name = "qwen"

    def __init__(self, _config: dict[str, Any] | None = None) -> None:
        self.client = QwenCliClient()

    @staticmethod
    def use_serve_by_default() -> bool:
        return os.environ.get("QWEN_USE_SERVE", "0").lower() not in {"0", "false", "no", "off"}

    async def run_stream(self, request: AgentRequest, on_output: AgentOutputCallback | None = None) -> AgentResult:
        use_serve = self.use_serve_by_default()
        if use_serve and not self.client.mock:
            try:
                output = await run_prompt_via_serve(
                    request.prompt,
                    request.cwd,
                    request.session_id,
                    on_output=on_output,
                    timeout_sec=self.client.timeout_sec,
                )
                return AgentResult(output=output, session_id=request.session_id, raw_output=output)
            except Exception as exc:
                fallback_enabled = os.environ.get("QWEN_SERVE_FALLBACK_CLI", "0").lower() not in {"0", "false", "no", "off"}
                if not fallback_enabled:
                    raise
                if on_output:
                    await on_output("stderr", f"Qwen serve failed; falling back to CLI: {exc}")

        output = await self.client.run_stream(
            request.prompt,
            request.cwd,
            request.session_id,
            on_output=on_output,
            run_id=request.run_id,
        )
        return AgentResult(output=output, session_id=request.session_id, raw_output=output)

    def command_preview(self, request: AgentRequest) -> str:
        use_serve = self.use_serve_by_default()
        if use_serve and not self.client.mock:
            return "POST qwen serve /session/<session>/prompt"
        return " ".join([*self.client.command(request.session_id, include_prompt_flag=False, cwd=request.cwd), "<prompt via stdin>"])

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": "qwen_serve" if self.use_serve_by_default() and not self.client.mock else "qwen_cli",
            "mock": self.client.mock,
            "bin": self.client.bin,
            "reuse_session": self.client.reuse_session,
            "bare": self.client.bare,
            "auth_type": self.client.auth_type or None,
            "timeout_sec": self.client.timeout_sec,
            "exists": self.client.mock or shutil.which(self.client.bin) is not None,
            "fallback": os.environ.get("QWEN_SERVE_FALLBACK_CLI", "0"),
        }
