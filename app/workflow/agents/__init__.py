from __future__ import annotations

from app.workflow.agents.base import AgentClient, AgentOutputCallback, AgentRequest, AgentResult, run_process_stream
from app.workflow.agents.providers.generic_cli import GenericCliAdapter
from app.workflow.agents.providers.opencode import OpenCodeCliAdapter
from app.workflow.agents.providers.qwen import QwenAdapter

__all__ = [
    "AgentClient",
    "AgentOutputCallback",
    "AgentRequest",
    "AgentResult",
    "GenericCliAdapter",
    "OpenCodeCliAdapter",
    "QwenAdapter",
    "run_process_stream",
]
