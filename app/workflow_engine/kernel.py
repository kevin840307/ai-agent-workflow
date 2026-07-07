from __future__ import annotations

from typing import Any

from .runner import WorkflowRunner


class WorkflowEngineKernel:
    """Thin local-first workflow kernel.

    Routes still call the historical runtime API, but the actual execute path is
    now represented by a kernel object. This gives us a stable seam for future
    store/event/step-executor migrations without changing UI/API contracts.
    """

    def __init__(self, *, executor: Any, actions: Any, store: Any, bus: Any) -> None:
        self.executor = executor
        self.actions = actions
        self.store = store
        self.bus = bus
        self.runner = WorkflowRunner(executor)

    async def execute(self, run_id: str, start_index: int = 0) -> None:
        return await self.runner.execute(run_id, start_index)

    def action_for_step(self, run: dict[str, Any], step_record: dict[str, Any], output_dir: Any):
        return self.actions.action_for_step(run, step_record, output_dir)

    def describe(self) -> dict[str, Any]:
        return {
            "schema": "aiwf.workflow-engine-kernel.v1",
            "executor": type(self.executor).__name__,
            "actions": type(self.actions).__name__,
            "store": type(self.store).__name__,
            "bus": type(self.bus).__name__,
        }
