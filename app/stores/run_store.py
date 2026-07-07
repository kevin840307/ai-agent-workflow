from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from app.core.paths import utc_now

ReadFn = Callable[[], Awaitable[dict[str, Any]]]
MutateFn = Callable[[Callable[[dict[str, Any]], Any]], Awaitable[Any]]


class RunStore(Protocol):
    async def get(self, run_id: str) -> dict[str, Any] | None: ...
    async def latest_for_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def list_active(self, statuses: set[str]) -> list[dict[str, Any]]: ...
    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]: ...
    async def mutate_run(self, run_id: str, fn: Callable[[dict[str, Any]], Any]) -> dict[str, Any] | None: ...
    async def transition_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
        ended: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None: ...


class FileRunStore:
    """File-backed RunStore abstraction around the existing JSON store."""

    def __init__(self, *, read: ReadFn, mutate: MutateFn) -> None:
        self._read = read
        self._mutate = mutate

    async def get(self, run_id: str) -> dict[str, Any] | None:
        data = await self._read()
        return next((run for run in data.get("runs", []) if run.get("id") == run_id), None)

    async def latest_for_session(self, session_id: str) -> dict[str, Any] | None:
        data = await self._read()
        runs = [run for run in data.get("runs", []) if run.get("session_id") == session_id]
        if not runs:
            return None
        return sorted(runs, key=lambda run: run.get("created_at", ""), reverse=True)[0]

    async def list_active(self, statuses: set[str]) -> list[dict[str, Any]]:
        return await self.list_by_status(statuses)

    async def list_by_status(self, statuses: set[str]) -> list[dict[str, Any]]:
        data = await self._read()
        return [run for run in data.get("runs", []) if run.get("status") in statuses]

    async def mutate_run(self, run_id: str, fn: Callable[[dict[str, Any]], Any]) -> dict[str, Any] | None:
        def apply(data: dict[str, Any]) -> dict[str, Any] | None:
            for run in data.get("runs", []):
                if run.get("id") == run_id:
                    fn(run)
                    return run
            return None

        return await self._mutate(apply)

    async def transition_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
        ended: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            run["status"] = status
            run["updated_at"] = utc_now()
            if ended:
                run["ended_at"] = utc_now()
            if error is not None:
                run["error"] = error
            elif status in {"queued", "running", "done"}:
                run["error"] = None
            if error_code is not None:
                run["error_code"] = error_code
            elif status in {"queued", "running", "done"}:
                run["error_code"] = None
            if extra:
                run.update(extra)

        return await self.mutate_run(run_id, apply)
