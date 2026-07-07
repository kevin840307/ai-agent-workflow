from __future__ import annotations

from typing import Any, Awaitable, Callable


class StepExecutor:
    def __init__(self, action_resolver: Callable[[dict[str, Any], dict[str, Any], Any], Callable[[], Awaitable[None]]]) -> None:
        self.action_resolver = action_resolver

    def action_for(self, run: dict[str, Any], step: dict[str, Any], output_dir: Any):
        return self.action_resolver(run, step, output_dir)
