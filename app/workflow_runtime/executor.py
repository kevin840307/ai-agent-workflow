from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import UserInputRequired, WorkflowCancelled, WorkflowError
from app.runtime_modules.run_owner import current_run_owner
from app.core.paths import read_text, utc_now, write_text
from app.core.metrics import metrics, now
from app.runtime_modules.files import project_file_snapshot, snapshot_changed

from .actions import WorkflowActions
from .error_codes import classify_exception
from .failure_classifier import classify_failure
from .retry_policy import retry_target_for_failure
from .step_utils import bool_config, expected_file_candidates, expected_files, format_exception, step_config, timeout_seconds
from .trace import write_run_trace_artifacts
from .agent_safety import write_agent_safety_report
from .event_log import append_event as append_workflow_event
from .run_lifecycle import cancel_requested, write_project_lock
from .artifact_policy import compact_run_diagnostics
from app.workflow_engine.state_machine import phase_for_step
from .retry_guard import should_stop_retry, clear_retry_history
from .recovery_counters import increment_recovery_counter, reset_consecutive_failures
from .run_diff import build_run_diff
from .scope_control import analyze_scope_delta
from .completion_gate import evaluate_completion


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
        transition_run_status: Callable[..., Awaitable[dict[str, Any] | None]] | None = None,
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
        self.transition_run_status = transition_run_status

    async def execute(self, run_id: str, start_index: int = 0) -> None:
        data = await self.store.read()
        run = next((item for item in data["runs"] if item["id"] == run_id), None)
        if not run:
            return
        run_dir = Path(run["workspace"])
        output_dir = run_dir / "output"
        run_started = now()
        try:
            if self.transition_run_status:
                running_run = await self.transition_run_status(
                    run_id,
                    "running",
                    extra={"run_owner": current_run_owner(), "started_at": run.get("started_at") or utc_now(), "ended_at": None},
                )
            else:
                running_run = await self.update_run(
                    run_id,
                    lambda r: r.update(
                        {
                            "status": "running",
                            "run_owner": current_run_owner(),
                            "started_at": r.get("started_at") or utc_now(),
                            "ended_at": None,
                            "error": None,
                            "updated_at": utc_now(),
                        }
                    ),
                )
            if running_run:
                run = running_run
                write_project_lock(run)
            await self.log(run, "workflow: started")

            # Actions close over this stable run object. Runtime-only flags such
            # as fresh-session recovery must be written here even when store
            # updates later return a replacement dict.
            action_run = run
            step_records = [item for item in action_run.get("steps", []) if item.get("status") != "disabled"]
            action_records = [
                (step_record["key"], self.actions.action_for_step(action_run, step_record, output_dir), step_record)
                for step_record in step_records
            ]
            key_to_index = {key: index for index, (key, _, _) in enumerate(action_records)}
            index = start_index
            while index < len(action_records):
                key, action, step_record = action_records[index]
                await self._raise_if_cancel_requested(run_id)
                try:
                    await self._run_step(run_id, action_run, key, action)
                    await self._raise_if_cancel_requested(run_id)
                    index += 1
                except UserInputRequired:
                    raise
                except Exception as exc:
                    base_retry_key = retry_target_for_failure(action_run, step_record, step_records, index, output_dir, error=exc)
                    if base_retry_key is None:
                        raise
                    if base_retry_key not in key_to_index:
                        await self.log(run, f"{key}: retry target {base_retry_key} is not in this workflow")
                        raise
                    retry_streaks = action_run.setdefault("retry_streaks", {})
                    source_retry_streak = int(retry_streaks.get(key, 0) or 0)
                    retry_key = retry_target_for_failure(
                        action_run,
                        step_record,
                        step_records,
                        index,
                        output_dir,
                        next_retry_count=source_retry_streak + 1,
                        error=exc,
                    )
                    if retry_key is None:
                        raise
                    if retry_key not in key_to_index:
                        await self.log(run, f"{key}: retry target {retry_key} is not in this workflow")
                        raise
                    if retry_key != base_retry_key:
                        await self.log(
                            run,
                            f"{key}: retry escalation {base_retry_key} -> {retry_key} on attempt {source_retry_streak + 1}",
                        )
                    # Retry budgets belong to the step that actually failed,
                    # not to the step selected as the repair target. This keeps
                    # AI Review from inheriting an exhausted Build budget.
                    source_retry_policy = step_record.get("retryPolicy") or (step_record.get("config") or {}).get("retryPolicy") or {}
                    policy_max_retries = source_retry_policy.get("maxRetries") if isinstance(source_retry_policy, dict) else None
                    max_retries = int(policy_max_retries or step_record.get("max_retries", 0) or 0)
                    if source_retry_streak >= max_retries:
                        message = (
                            f"Retry stopped: {key} already reached its consecutive retry budget "
                            f"({source_retry_streak}/{max_retries}). Repair target was {retry_key}: {exc}"
                        )
                        await self.set_step(run_id, key, "failed", message, error_code=classify_exception(message))
                        await self.log(action_run, f"{key}: consecutive retry budget reached; repair target={retry_key}: {exc}")
                        raise WorkflowError(message) from exc
                    failure_code = str(classify_failure(exc, step_key=key).get("code") or "UNKNOWN")
                    if failure_code == "TIMEOUT":
                        # Reusing the same timed-out conversation commonly repeats
                        # the same stalled behavior. Force the next agent call,
                        # whichever repair step it belongs to, onto a fresh session.
                        action_run["_fresh_agent_session_once"] = True
                        await self.log(action_run, f"{key}: timeout recovery will use a fresh agent session")

                    source_retry_streak += 1
                    retry_streaks[key] = source_retry_streak
                    def persist_retry_streak(item: dict[str, Any]) -> None:
                        item.setdefault("retry_streaks", {})[key] = source_retry_streak
                        increment_recovery_counter(item, "agent_attempts")
                        increment_recovery_counter(item, "consecutive_failures")
                        if failure_code == "TIMEOUT":
                            item["_fresh_agent_session_once"] = True
                            increment_recovery_counter(item, "session_restarts")
                        if retry_key != key and any(token in str(retry_key).lower() for token in ("plan", "prompt")):
                            increment_recovery_counter(item, "replans")
                        if bool(classify_failure(exc, step_key=key).get("auto_repairable")):
                            increment_recovery_counter(item, "deterministic_repairs")
                    latest_streak = await self.update_run(run_id, persist_retry_streak)
                    if latest_streak:
                        run = latest_streak

                    # Reliability guard: stop deterministic retry loops before local runs
                    # burn the whole retry budget on the same failure text.  The
                    # history is stored on the run so crash/restart/debug bundles
                    # can explain why a retry stopped.
                    guard_payload: dict[str, Any] = {}
                    def update_retry_guard_history(item: dict[str, Any]) -> None:
                        nonlocal guard_payload
                        stop, stop_reason, attempt = should_stop_retry(
                            item,
                            step_key=key,
                            error=exc,
                            task_id=self._task_id_from_error(exc),
                            retry_target=retry_key,
                        )
                        attempt["stop"] = stop
                        attempt["stop_reason"] = stop_reason
                        guard_payload = attempt
                    latest_for_guard = await self.update_run(run_id, update_retry_guard_history)
                    if latest_for_guard:
                        run = latest_for_guard
                    if guard_payload.get("stop"):
                        message = str(guard_payload.get("stop_reason") or f"Retry loop guard stopped {retry_key}.")
                        await self.set_step(run_id, key, "failed", message, error_code="RETRY_LOOP_DETECTED")
                        await self.log(run, message)
                        raise WorkflowError(message) from exc
                    if self._same_failure_repeated(run, key, exc):
                        await self.log(run, f"{key}: same failure observed again; retry target={retry_key}; retry guard count={guard_payload.get('same_failure_count')}: {exc}")
                    retry_count = await self.increment_step_retry(run_id, key)
                    target_index = key_to_index[retry_key]
                    await self.append_failure_feedback(action_run, key, retry_key, exc, retry_count, max_retries)
                    await self.log(action_run, f"{key}: failed, retrying from {retry_key} ({retry_count}/{max_retries}): {exc}")
                    reset_run = await self.reset_steps_from(run_id, target_index)
                    if reset_run:
                        # Keep the stable object captured by all step actions, but
                        # refresh it from the authoritative Store after a retry reset.
                        # Some Store adapters return the exact same dict object. Take
                        # a deep snapshot before clearing, otherwise the synchronization
                        # erases the Run itself and the next retry loses workspace/steps.
                        refreshed_run = copy.deepcopy(reset_run)
                        action_run.clear()
                        action_run.update(refreshed_run)
                        run = action_run
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


    async def _raise_if_cancel_requested(self, run_id: str) -> None:
        data = await self.store.read()
        current = next((item for item in data.get("runs", []) if item.get("id") == run_id), None)
        if cancel_requested(current or {}):
            raise asyncio.CancelledError("Workflow cancellation requested by user.")

    async def _run_step(self, run_id: str, run: dict[str, Any], key: str, action: Callable[[], Awaitable[None]]) -> None:
        step_record = next((item for item in run.get("steps", []) if item.get("key") == key), {})
        await self.set_step(run_id, key, "running")
        await self.log(run, f"{key}: started")
        step_started = now()
        before_project_snapshot = self._project_snapshot_if_required(run, step_record)
        if self.record_step_event:
            await self.record_step_event(run_id, key, "started", f"{key}: started")
        try:
            timeout = timeout_seconds(step_record)
            config = step_config(step_record)
            if bool_config(config, "enableTaskLoop", False):
                # Task-loop actions enforce a fresh timeout per task. A single
                # outer countdown would unfairly consume later tasks' budgets.
                await action()
            elif timeout:
                await asyncio.wait_for(action(), timeout=timeout)
            else:
                await action()
            self._validate_expected_files(run, step_record)
            self._validate_project_changes(run, step_record, before_project_snapshot)
        except asyncio.TimeoutError as exc:
            message = f"{key}: timed out after {timeout_seconds(step_record) or 0:.0f} seconds."
            await self.set_step(run_id, key, "failed", message, error_code=classify_exception(message))
            metrics.increment("workflow.step.failed")
            metrics.observe("workflow.step.durationSec", now() - step_started)
            if self.record_step_event:
                await self.record_step_event(run_id, key, "failed", message)
            raise WorkflowError(message) from exc
        except UserInputRequired as exc:
            await self.set_step(run_id, key, "waiting_input", str(exc), error_code=classify_exception(exc))
            if self.record_step_event:
                await self.record_step_event(run_id, key, "waiting_input", str(exc))
            raise
        except Exception as exc:
            await self.set_step(run_id, key, "failed", str(exc), error_code=classify_exception(exc))
            metrics.increment("workflow.step.failed")
            metrics.observe("workflow.step.durationSec", now() - step_started)
            if self.record_step_event:
                await self.record_step_event(run_id, key, "failed", str(exc))
            raise
        await self.set_step(run_id, key, "passed")
        # Successful completion resets only the consecutive failure streak. The
        # cumulative retry_count remains available for reports and scoring.
        run.setdefault("retry_streaks", {})[key] = 0
        # Actions mutate the stable in-memory Run with validation evidence, task
        # checkpoints, and session handoff state. Persist those authoritative
        # fields before a repository snapshot can overwrite them.
        validation_results_snapshot = json.loads(json.dumps(run.get("validation_results") or []))
        task_checkpoints_snapshot = json.loads(json.dumps(run.get("task_checkpoints") or []))
        tasks_snapshot = json.loads(json.dumps(run.get("tasks") or []))
        last_task_checkpoint_snapshot = run.get("last_task_checkpoint_id")
        recovery_counters_snapshot = json.loads(json.dumps(run.get("recovery_counters") or {}))

        def clear_guard(item: dict[str, Any]) -> None:
            item["validation_results"] = validation_results_snapshot
            item["task_checkpoints"] = task_checkpoints_snapshot
            item["tasks"] = tasks_snapshot
            item["last_task_checkpoint_id"] = last_task_checkpoint_snapshot
            item["recovery_counters"] = recovery_counters_snapshot
            clear_retry_history(item, step_key=key)
            item.setdefault("retry_streaks", {})[key] = 0
            reset_consecutive_failures(item)
            persisted_step = next((candidate for candidate in item.get("steps", []) if candidate.get("key") == key), None)
            item["phase"] = phase_for_step(persisted_step, item.get("status"))
            checkpoints = item.setdefault("checkpoints", [])
            checkpoints.append(
                {
                    "id": f"step-{key}-{len(checkpoints) + 1}",
                    "kind": "step_completed",
                    "step_key": key,
                    "status": "passed",
                    "created_at": utc_now(),
                    "retry_count": int((persisted_step or {}).get("retry_count") or 0),
                    "changed_files": list(item.get("changed_files") or [])[-100:],
                }
            )
            if len(checkpoints) > 100:
                item["checkpoints"] = checkpoints[-100:]
            item["last_checkpoint_id"] = item["checkpoints"][-1]["id"]
        latest = await self.update_run(run_id, clear_guard)
        if latest:
            run.update(latest)
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

    def _project_snapshot_if_required(self, run: dict[str, Any], step_record: dict[str, Any]) -> dict[str, tuple[int, int]] | None:
        config = step_config(step_record)
        key = str(step_record.get("key") or "")
        # General Auto Development performs its own direct-edit diff validation
        # inside build/generate_tests.  The outer step-level snapshot can be
        # misleading on retries where already-satisfied tasks are skipped, so do
        # not force a second project-diff gate here.
        if str(run.get("workflow_id") or "") == "general-auto-development" and key in {"build", "generate_tests"}:
            return None
        require_changes = bool_config(config, "requireProjectChanges", False) or bool_config(config, "projectDiffGate", False)
        if not require_changes:
            return None
        return project_file_snapshot(Path(run.get("project_path") or run["workspace"]))

    def _validate_project_changes(
        self,
        run: dict[str, Any],
        step_record: dict[str, Any],
        before_snapshot: dict[str, tuple[int, int]] | None,
    ) -> None:
        if before_snapshot is None:
            return
        project_dir = Path(run.get("project_path") or run["workspace"])
        after_snapshot = project_file_snapshot(project_dir)
        if not snapshot_changed(before_snapshot, after_snapshot):
            raise WorkflowError(
                f"{step_record.get('key')}: project changes were required, but no files changed under Project Path: {project_dir}"
            )

    @staticmethod
    def _task_id_from_error(exc: BaseException | str) -> str | None:
        match = re.search(r"\bTASK-\d{3}\b", str(exc), flags=re.IGNORECASE)
        return match.group(0).upper() if match else None

    def _same_failure_repeated(self, run: dict[str, Any], target_key: str, exc: BaseException) -> bool:
        feedback = read_text(Path(run["workspace"]) / "input" / "failure-feedback.md")
        if not feedback.strip():
            return False
        target_blocks = re.findall(
            rf"^## Retry Feedback for {re.escape(target_key)}\s*$.*?(?=^## Retry Feedback for |\Z)",
            feedback,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not target_blocks:
            return False
        current = self._failure_fingerprint(str(exc))
        return any(current and current == self._failure_fingerprint(self._feedback_error_text(block)) for block in target_blocks)

    @staticmethod
    def _feedback_error_text(block: str) -> str:
        marker = "### Error message to fix"
        if marker not in block:
            return block
        return block.split(marker, 1)[1].strip()

    @staticmethod
    def _failure_fingerprint(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        normalized = re.sub(r"0x[0-9a-f]+", "0xADDR", normalized)
        normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}t[^ ]+", "TIMESTAMP", normalized)
        return normalized[:800]

    async def _finalize_artifacts(self, run_id: str, final_run: dict[str, Any]) -> None:
        """Refresh user-facing artifacts, archive verbose diagnostics, then refresh index."""
        await self.refresh_artifacts(run_id)
        compact_run_diagnostics(final_run, force=True)
        await self.refresh_artifacts(run_id)

    async def _mark_done(self, run_id: str, run: dict[str, Any], run_dir: Path) -> None:
        # Final status is an atomic evidence decision. Always evaluate the latest
        # persisted Run because retry/reset/session updates may replace the Store
        # object while actions intentionally retain a stable in-memory reference.
        data = await self.store.read()
        latest_run = next((item for item in data.get("runs", []) if item.get("id") == run_id), None)
        if latest_run:
            # Store adapters may return the same mutable dict object. Snapshot it
            # before refreshing the stable in-memory Run or clear() would erase
            # the authoritative state itself.
            latest_snapshot = copy.deepcopy(latest_run)
            run.clear()
            run.update(latest_snapshot)
        # A workflow cannot become done when required tests/validation or task
        # state are missing.
        completion = evaluate_completion(run, output_dir=run_dir / "output")
        write_text(run_dir / "output" / "completion-gate.json", json.dumps(completion, indent=2, ensure_ascii=False))
        if completion.get("status") != "PASS":
            raise WorkflowError("FINAL_COMPLETION_GATE_FAILED: " + "; ".join(completion.get("errors") or []))

        def finish(r: dict[str, Any]) -> None:
            r["status"] = "done"
            r["error"] = None
            r["error_code"] = None
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        final_run = await self.transition_run_status(run_id, "done", ended=True) if self.transition_run_status else await self.update_run(run_id, finish)
        if not final_run:
            final_run = dict(run)
            finish(final_run)
        try:
            diff = build_run_diff(final_run, run_dir)
            files = diff.get("files") or diff.get("changes") or []
            scope_delta = analyze_scope_delta(
                read_text(run_dir / "requirement.md"),
                file_changes=files,
                planned_tasks=list(final_run.get("tasks") or []),
            )
            final_run["scope_delta"] = scope_delta
            write_text(run_dir / "output" / "scope-delta.json", json.dumps(scope_delta, indent=2, ensure_ascii=False))
        except Exception as exc:
            final_run["scope_delta"] = {"status": "unknown", "error": str(exc)}
        write_text(run_dir / ".workflow" / "state.json", json.dumps(final_run, indent=2, ensure_ascii=False))
        write_run_trace_artifacts(final_run, run_dir)
        write_agent_safety_report(final_run)
        append_workflow_event(final_run, "run.completed", message="workflow: done", status="done")
        await self._finalize_artifacts(run_id, final_run)
        await self.log(run, "workflow: done")
        await self.bus.publish(run_id, {"type": "done"})

    async def _mark_waiting_input(self, run_id: str, run: dict[str, Any], run_dir: Path, exc: UserInputRequired) -> None:
        await self.log(run, f"workflow: waiting for user input: {exc}")

        def wait(r: dict[str, Any]) -> None:
            r["status"] = "waiting_input"
            r["error"] = str(exc)
            r["error_code"] = classify_exception(exc)
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        waiting_run = await self.transition_run_status(run_id, "waiting_input", error=str(exc), error_code=classify_exception(exc), ended=True) if self.transition_run_status else await self.update_run(run_id, wait)
        if not waiting_run:
            waiting_run = dict(run)
            wait(waiting_run)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(waiting_run, indent=2, ensure_ascii=False))
        write_run_trace_artifacts(waiting_run, run_dir)
        write_agent_safety_report(waiting_run)
        append_workflow_event(waiting_run, "run.waiting_input", message=str(exc), status="waiting_input", error_code=waiting_run.get("error_code"))
        await self.refresh_artifacts(run_id)
        await self.bus.publish(run_id, {"type": "waiting_input", "error": str(exc)})

    async def _mark_cancelled(self, run_id: str, run: dict[str, Any], run_dir: Path) -> None:
        await self.log(run, "workflow: cancelled")

        def cancel(r: dict[str, Any]) -> None:
            r["status"] = "cancelled"
            r["error"] = "Workflow cancelled by user."
            r["error_code"] = classify_exception(WorkflowCancelled(r["error"]))
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()
            for step in r.get("steps", []):
                if step.get("status") == "running":
                    step["status"] = "cancelled"
                    step["error"] = r["error"]
                    step["ended_at"] = utc_now()

        cancelled_run = await self.transition_run_status(run_id, "cancelled", error="Workflow cancelled by user.", error_code=classify_exception(WorkflowCancelled("Workflow cancelled by user.")), ended=True) if self.transition_run_status else await self.update_run(run_id, cancel)
        if cancelled_run:
            def cancel_running_steps(r: dict[str, Any]) -> None:
                for step in r.get("steps", []):
                    if step.get("status") == "running":
                        step["status"] = "cancelled"
                        step["error"] = r.get("error")
                        step["ended_at"] = utc_now()
            cancelled_run = await self.update_run(run_id, cancel_running_steps) or cancelled_run
        if not cancelled_run:
            fallback_run = dict(run)
            cancel(fallback_run)
            cancelled_run = fallback_run
        write_text(run_dir / ".workflow" / "state.json", json.dumps(cancelled_run, indent=2, ensure_ascii=False))
        write_run_trace_artifacts(cancelled_run, run_dir)
        write_agent_safety_report(cancelled_run)
        append_workflow_event(cancelled_run, "run.cancelled", message="Workflow cancelled by user.", status="cancelled", error_code=cancelled_run.get("error_code"))
        await self._finalize_artifacts(run_id, cancelled_run)
        await self.bus.publish(run_id, {"type": "cancelled", "error": "Workflow cancelled by user."})

    async def _mark_failed(self, run_id: str, run: dict[str, Any], run_dir: Path, exc: Exception) -> None:
        error = format_exception(exc)
        error_code = classify_exception(exc)
        await self.log(run, f"workflow: failed: {error}")

        def fail(r: dict[str, Any]) -> None:
            r["status"] = "failed"
            r["error"] = str(error)
            r["error_code"] = error_code
            r["ended_at"] = utc_now()
            r["updated_at"] = utc_now()

        failed_run = await self.transition_run_status(run_id, "failed", error=str(error), error_code=error_code, ended=True) if self.transition_run_status else await self.update_run(run_id, fail)
        if not failed_run:
            failed_run = dict(run)
            fail(failed_run)
        write_text(run_dir / ".workflow" / "state.json", json.dumps(failed_run, indent=2, ensure_ascii=False))
        write_run_trace_artifacts(failed_run, run_dir)
        write_agent_safety_report(failed_run)
        append_workflow_event(failed_run, "run.failed", message=str(error), status="failed", error_code=error_code)
        await self._finalize_artifacts(run_id, failed_run)
        await self.bus.publish(run_id, {"type": "failed", "error": str(error)})
