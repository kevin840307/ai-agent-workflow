from __future__ import annotations

from typing import Any


class WorkflowEventBus:
    def __init__(self, event_store: Any | None = None, live_bus: Any | None = None) -> None:
        self.event_store = event_store
        self.live_bus = live_bus

    async def append(self, run_id: str, event: dict[str, Any]) -> None:
        if self.event_store:
            await self.event_store.append(run_id, event)
        if self.live_bus:
            await self.live_bus.publish(run_id, {"type": "event", "event": event})
