from __future__ import annotations

from typing import Any


class WorkflowRunner:
    def __init__(self, executor: Any) -> None:
        self.executor = executor

    async def execute(self, run_id: str, start_index: int = 0) -> None:
        return await self.executor.execute(run_id, start_index)
