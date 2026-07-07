from __future__ import annotations

from typing import Any


class WorkflowTransitionService:
    """Small transition facade used by the local engine kernel.

    It intentionally depends on Store-like objects instead of JSON files so the
    same engine code can run on file or SQLite backends.
    """

    def __init__(self, run_store: Any | None = None, step_store: Any | None = None) -> None:
        self.run_store = run_store
        self.step_store = step_store

    async def run_status(self, run_id: str, status: str, **kwargs: Any) -> dict[str, Any] | None:
        if not self.run_store:
            return None
        return await self.run_store.transition_status(run_id, status, **kwargs)

    async def step_status(self, run_id: str, step_key: str, status: str, **kwargs: Any) -> dict[str, Any] | None:
        if not self.step_store:
            return None
        return await self.step_store.mark(run_id, step_key, status, **kwargs)
