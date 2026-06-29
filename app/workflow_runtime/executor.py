from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import UserInputRequired, WorkflowError
from app.runtime_modules.paths import utc_now, write_text
from app.runtime_modules.metrics import metrics, now

from .actions import WorkflowActions
from .retry_policy import retry_target_for_failure
from .step_utils import expected_file_candidates, expected_files, format_exception, timeout_seconds


class WorkflowExecutor:
    def __init__(
        self,
        *,
        store: Any,
        bus: Any,
        actions: WorkflowActions,
        update_run: Callable[[str, Callable[[dict[str, Any]], Any]], Awaitable[dict[str, Any]]],
        set_step: Callable[..., Awaitable[Any]],
        reset_steps_from: Callable[[str, int], Awaitable[Any]],
        get_step_retry_count: Callable[[str, str], Awaitable[int]],
        increment_step_retry: Callable[[str, str], Awaitable[int]],
        append_failure_feedback: Callable[..., Awaitable[Any]],
        refresh_artifacts: Callable[[str], Awaitable[Any]],
        log: Callable[[dict[str, Any], str], Awaitable[None]],
        record_step_event: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.actions = actions
        self.update_run = update_run
        self.set_step = set_step
        self.reset_steps_from = reset_steps_from
        self.get_step_retry_count = get_step_retry_count
        self.increment_step_retry = increment_step_retry
        self.append_failure_feedback = append_failure_feedback
        self.refresh_artifacts = refresh_artifacts
        self.log = log
        self.record_step_event = record_step_event

    async def execute(self, run_id: str, start_index: int = 0) -> None:
        data = await self.store.read()
        run = next((item for item in data["runs"] if item["id"] == run_id), None)
        if not run:
            return
        run_dir = Path(run["workspace"])
        output_dir = run_dir / "output"
        run_started = now()
        try:
            await self.update_run(
                run_id,
                lambda r: r.update(
                    {
                        "status": "running",
                        "started_at": r.get("started_at") or utc_now(),
                        "ended_at": None,
                        "error": None,
                        "updated_at": utc_now(),
                    }
                ),
            )
            await self.log(run, "workflow: started")

            step_records = [item for item in run.get("steps", []) if item.get("status") != "disabled"]
            action_records = [
                (step_record["key"], self.actions.action_for_step(run, step_record, output_dir), step_record)
                for step_record in step_records
            ]
            key_to_index = {key: index for index, (key, _, _) in enumerate(action_records)}
            index = start_index
            while index < len(action_records):
                key, action, step_record = action_records[index]
                try:
                    await self._run_step(run_id, run, key, action)
                    index += 1
                except UserInputRequired:
                    raise
                except Exception as exc:
                    retry_key = retry_target_for_failure(run, step_record, step_records, index, output_dir)
                    if retry_key is None:
                        raise
                    if retry_key not in key_to_index:
                        await self.log(run, f"{key}: retry target {retry_key} is not in this workflow")
                        raise
                    retry_step_record = next((item for item in step_records if item.get("key") == retry_key), step_record)
                    max_retries = int(retry_step_record.get("max_retries", step_record.get("max_retries", 0)) or 0)
                    current_retry_count = await self.get_step_retry_count(run_id, retry_key)
                    if current_retry_count >= max_retries:
                        message = (
                            f"Retry stopped: {retry_key} already reached max retries "
                            f"({current_retry_count}/{max_retries}). Last failure from {key}: {exc}"
                        )
                        await self.set_step(run_id, key, "failed", message)
                        await self.log(run, f"{key}: max retries reached for {retry_key}: {exc}")
                        raise WorkflowError(message) from exc
                    retry_count = await self.increment_step_retry(run_id, retry_key)
                    target_index = key_to_index[retry_key]
                    await self.append_failure_feedback(run, key, retry_key, exc, retry_count, max_retries)
                    await self.log(run, f"{key}: failed, retrying from {retry_key} ({retry_count}/{max_retries}): {exc}")
                    await self.reset_steps_from(run_id, target_index)
                    index = target_index

            await self._mark_done(run_id, run, run_dir)
            metrics.observe("workflow.durationSec", now() - run_started)
        except UserInputRequired as exc:
            await self._mark_waiting_input(run_id, run, run_dir, exc)
        except asyncio.CancelledError:
            await self._mark_cancelled(run_id, run, run_dir)
            metrics.increment("workflow.cancelled")
            raise
        except Exception as exc:
            await self._mark_failed(run_id, run, run_dir, exc)
            metrics.increment("workflow.failed")
            metrics.observe("workflow.durationSec", now() - run_started)

    async def _run_step(self, run_id: str, run: dict[str, Any], key: str, action: Callable[[], Awaitable[None]]) -> None:
        step_record = next((item for item in run.get("steps", []) if item.get("key") == key), {})
        await self.set_step(run_id, key, "running")
        await self.log(run, f"{key}: started")
        step_started = now()
        if self.record_step_event:
            await self.record_step_event(run_id, key, "started", f"{key}: started")
        try:
            timeout = timeout_seconds(step_record)
            if timeout:
                await asyncio.wait_for(action(), timeout=timeout)
            else:
                await action()
            self._validate_expected_files(run, step_record)
        except asyncio.TimeoutError as exc:
            message = f"{key}: timed out after {timeout_seconds(step_record) or 0:.0f} seconds."
            await self.set_step(run_id, key, "failed", message)
            metrics.increment("workflow.step.failed")
            metrics.observe("workflow.step.durationSec", now() - step_started)
            if self.record_step_event:
                await self.record_step_event(run_id, key, "failed", message)
            raise WorkflowError(message) from exc
        except UserInputRequired as exc:
            await self.set_step(run_id, key, "waiting_input", str(exc))
            if self.record_step_event:
                await self.record_step_event(run_id, key, "waiting_input", str(exc))
            raise
        except Exception as exc:
            await self.set_step(run_id, key, "failed", str(exc))
            metrics.increment("workflow.step.failed")
            metrics.observe("workflow.step.durationSec", now() - step_started)
            if self.record_step_event:
                await self.record_step_event(run_id, key, "failed", str(exc))
            raise
        await self.set_step(run_id, key, "passed")
        metrics.observe("workflow.step.durationSec", now() - step_started)
        if self.record_step_event:
            await self.record_step_event(run_id, key, "passed", f"{key}: passed")
        await self.log(run, f"{key}: passed")

    def _validate_expected_files(self, run: dict[str, Any], step_record: dict[str, Any]) -> None:
        missing: list[str] = []
        for rel_path in expected_files(step_record):
            candidates = expected_file_candidates(run, rel_path)
            if not any(path.exists() and path.is_file() for path in candidates):
                missing.append(rel_path)
        if missing:
            raise WorkflowError(f"{step_record.get('key')}: expected file(s) not found: {', '.join(missing)}")

    async def _mark_done(self, run_id: str, run: dict[str, Any], run_dir: Path) -> None:
        def finish(r: dict[str, Any]) -> None:
            r["status"] = "done"
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        final_run = await self.update_run(run_id, finish)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(final_run, indent=2, ensure_ascii=False))
        await self.refresh_artifacts(run_id)
        await self.log(run, "workflow: done")
        await self.bus.publish(run_id, {"type": "done"})

    async def _mark_waiting_input(self, run_id: str, run: dict[str, Any], run_dir: Path, exc: UserInputRequired) -> None:
        await self.log(run, f"workflow: waiting for user input: {exc}")

        def wait(r: dict[str, Any]) -> None:
            r["status"] = "waiting_input"
            r["error"] = str(exc)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        waiting_run = await self.update_run(run_id, wait)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(waiting_run, indent=2, ensure_ascii=False))
        await self.refresh_artifacts(run_id)
        await self.bus.publish(run_id, {"type": "waiting_input", "error": str(exc)})

    async def _mark_cancelled(self, run_id: str, run: dict[str, Any], run_dir: Path) -> None:
        await self.log(run, "workflow: cancelled")

        def cancel(r: dict[str, Any]) -> None:
            r["status"] = "cancelled"
            r["error"] = "Workflow cancelled by user."
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()
            for step in r.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "cancelled"
                    step["error"] = r["error"]
                    step["ended_at"] = utc_now()

        cancelled_run = await self.update_run(run_id, cancel)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(cancelled_run, indent=2, ensure_ascii=False))
        await self.refresh_artifacts(run_id)
        await self.bus.publish(run_id, {"type": "cancelled", "error": "Workflow cancelled by user."})

    async def _mark_failed(self, run_id: str, run: dict[str, Any], run_dir: Path, exc: Exception) -> None:
        error = format_exception(exc)
        await self.log(run, f"workflow: failed: {error}")

        def fail(r: dict[str, Any]) -> None:
            r["status"] = "failed"
            r["error"] = str(error)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        failed_run = await self.update_run(run_id, fail)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(failed_run, indent=2, ensure_ascii=False))
        await self.refresh_artifacts(run_id)
        await self.bus.publish(run_id, {"type": "failed", "error": str(error)})
