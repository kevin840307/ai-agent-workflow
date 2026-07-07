from __future__ import annotations

from typing import Any, Protocol

from app.core.paths import utc_now

from .run_store import RunStore


class EventStore(Protocol):
    async def append(self, run_id: str, event: dict[str, Any]) -> dict[str, Any] | None: ...
    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]: ...


class FileEventStore:
    """Run-scoped event store backed by the existing run record.

    The canonical durable stream remains `.workflow/events.jsonl`; this store
    keeps a compact copy on the run object for API/UI state reconciliation and
    future SQLite migration.
    """

    def __init__(self, run_store: RunStore) -> None:
        self._run_store = run_store

    async def append(self, run_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
        payload = dict(event)
        payload.setdefault("ts", utc_now())
        payload.setdefault("time", payload["ts"])

        def apply(run: dict[str, Any]) -> None:
            run.setdefault("events", []).append(payload)
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)

    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        run = await self._run_store.get(run_id)
        return list((run or {}).get("events", []))
