from __future__ import annotations

from typing import Any, Protocol

from app.core.paths import utc_now

from .run_store import RunStore


class StepStore(Protocol):
    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]: ...
    async def get(self, run_id: str, step_key: str) -> dict[str, Any] | None: ...
    async def mark(
        self,
        run_id: str,
        step_key: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any] | None: ...
    async def append_event(self, run_id: str, step_key: str, event: dict[str, Any]) -> dict[str, Any] | None: ...
    async def reset_from(self, run_id: str, start_index: int) -> dict[str, Any] | None: ...
    async def reset_retry_counts_from(self, run_id: str, start_index: int) -> dict[str, Any] | None: ...
    async def increment_retry(self, run_id: str, step_key: str) -> tuple[dict[str, Any] | None, int]: ...


class FileStepStore:
    def __init__(self, run_store: RunStore) -> None:
        self._run_store = run_store

    async def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        run = await self._run_store.get(run_id)
        return list((run or {}).get("steps", []))

    async def get(self, run_id: str, step_key: str) -> dict[str, Any] | None:
        return next((step for step in await self.list_for_run(run_id) if step.get("key") == step_key), None)

    async def mark(
        self,
        run_id: str,
        step_key: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            for step in run.get("steps", []):
                if step.get("key") == step_key:
                    step["status"] = status
                    if status == "running":
                        step["started_at"] = utc_now()
                        step["ended_at"] = None
                        step["error"] = None
                        step["error_code"] = None
                    if status in {"passed", "failed", "skipped", "waiting_input", "cancelled"}:
                        step["ended_at"] = utc_now()
                        step["error"] = error
                        step["error_code"] = error_code
                    break
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)

    async def append_event(self, run_id: str, step_key: str, event: dict[str, Any]) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            run.setdefault("timeline", []).append(event)
            for step in run.get("steps", []):
                if step.get("key") == step_key:
                    step.setdefault("events", []).append(event)
                    step["last_event"] = event.get("message") or event.get("type") or "event"
                    if event.get("kind") == "retry" or event.get("type") == "retry":
                        step.setdefault("retry_history", []).append(event)
                    break
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)
    async def reset_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            for index, step in enumerate(run.get("steps", [])):
                if index >= start_index:
                    step["status"] = "pending"
                    step["started_at"] = None
                    step["ended_at"] = None
                    step["error"] = None
                    step["error_code"] = None
            run["status"] = "queued"
            run["error"] = None
            run["error_code"] = None
            run["ended_at"] = None
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)

    async def reset_retry_counts_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        def apply(run: dict[str, Any]) -> None:
            for index, step in enumerate(run.get("steps", [])):
                if index >= start_index:
                    step["retry_count"] = 0
                    step["manual_retry_started_at"] = utc_now()
            run["updated_at"] = utc_now()

        return await self._run_store.mutate_run(run_id, apply)

    async def increment_retry(self, run_id: str, step_key: str) -> tuple[dict[str, Any] | None, int]:
        value = 0

        def apply(run: dict[str, Any]) -> None:
            nonlocal value
            for step in run.get("steps", []):
                if step.get("key") == step_key:
                    value = int(step.get("retry_count", 0) or 0) + 1
                    step["retry_count"] = value
                    break
            run["updated_at"] = utc_now()

        run = await self._run_store.mutate_run(run_id, apply)
        return run, value

