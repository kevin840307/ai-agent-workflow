from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self.queues: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self.queues.get(run_id, set())):
            await queue.put(event)

    async def subscribe(self, run_id: str):
        queue: asyncio.Queue = asyncio.Queue()
        self.queues.setdefault(run_id, set()).add(queue)
        try:
            yield queue
        finally:
            self.queues.get(run_id, set()).discard(queue)
