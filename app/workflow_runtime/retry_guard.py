from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .failure_classifier import classify_failure
from .progress_evaluator import capture_progress, compare_progress, progress_signature as _progress_signature

DEFAULT_REPEATED_FAILURE_LIMIT = int(os.environ.get("AIWF_RETRY_REPEATED_FAILURE_LIMIT", "3") or 3)
NO_FILE_CHANGE_LIMIT = int(os.environ.get("AIWF_RETRY_NO_FILE_CHANGE_LIMIT", "2") or 2)

_DEFAULT_BUDGET: dict[str, int] = {
    # Generous enough for small local models, but bounded across changing error text.
    "maxRunFailures": 40,
    "maxStepFailures": 24,
    "maxTaskFailures": 12,
    "maxFailureClass": 12,
    "maxFingerprint": 9,
    "wallClockMinutes": 60,
    "freshSessionEvery": 3,
}


def progress_signature(run: dict[str, Any], project_path: str | Path | None = None) -> str:
    return _progress_signature(capture_progress(run, project_path))


def failure_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    normalized = re.sub(r"0x[0-9a-f]+", "0xADDR", normalized)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}t[^ ]+", "TIMESTAMP", normalized)
    return hashlib.sha256(normalized[:2000].encode("utf-8", errors="replace")).hexdigest()[:16]


def is_no_file_change_error(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        token in lower
        for token in [
            "no files changed",
            "no file change",
            "project changes were required",
            "did not create or modify",
            "did not directly create or modify",
            "expected file(s) not found",
            "no_file_change",
        ]
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _step_record(run: dict[str, Any], step_key: str) -> dict[str, Any]:
    return next((item for item in run.get("steps", []) if item.get("key") == step_key), {})


def recovery_budget(run: dict[str, Any], step_key: str) -> dict[str, int]:
    budget = dict(_DEFAULT_BUDGET)
    step = _step_record(run, step_key)
    config = step.get("config") if isinstance(step.get("config"), dict) else {}
    retry_policy = step.get("retryPolicy") if isinstance(step.get("retryPolicy"), dict) else {}
    candidates = [
        run.get("recoveryBudget"),
        run.get("recovery_budget"),
        step.get("recoveryBudget"),
        config.get("recoveryBudget"),
        retry_policy.get("recoveryBudget"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key, default in _DEFAULT_BUDGET.items():
            if key in candidate:
                budget[key] = _positive_int(candidate.get(key), default)
    # Environment variables are operational overrides, not task-specific logic.
    env_map = {
        "maxRunFailures": "AIWF_RETRY_MAX_RUN_FAILURES",
        "maxStepFailures": "AIWF_RETRY_MAX_STEP_FAILURES",
        "maxTaskFailures": "AIWF_RETRY_MAX_TASK_FAILURES",
        "maxFailureClass": "AIWF_RETRY_MAX_FAILURE_CLASS",
        "maxFingerprint": "AIWF_RETRY_MAX_FINGERPRINT",
        "wallClockMinutes": "AIWF_RETRY_WALL_CLOCK_MINUTES",
        "freshSessionEvery": "AIWF_RETRY_FRESH_SESSION_EVERY",
    }
    for key, env_name in env_map.items():
        if env_name in os.environ:
            budget[key] = _positive_int(os.environ.get(env_name), budget[key])
    return budget


def _elapsed_minutes(run: dict[str, Any]) -> float:
    raw = run.get("started_at") or run.get("created_at")
    if not raw:
        return 0.0
    try:
        started = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds() / 60.0)
    except (TypeError, ValueError):
        return 0.0


def _increment(mapping: dict[str, Any], key: str) -> int:
    value = int(mapping.get(key, 0) or 0) + 1
    mapping[key] = value
    return value


def record_failure_attempt(
    run: dict[str, Any],
    *,
    step_key: str,
    error: BaseException | str,
    task_id: str | None = None,
    retry_target: str | None = None,
    progress: str | None = None,
) -> dict[str, Any]:
    text = str(error)
    fp = failure_fingerprint(text)
    failure_class = str(classify_failure(text, step_key=step_key).get("code") or "UNKNOWN")
    task = str(task_id or "")
    history = run.setdefault("retry_guard_history", [])

    def same_scope(item: dict[str, Any]) -> bool:
        return (
            (item.get("source_step") or item.get("step_key")) == step_key
            and str(item.get("task_id") or "") == task
            and str(item.get("failure_class") or failure_class) == failure_class
        )

    current_snapshot = capture_progress(run, run.get("project_path"))
    previous_entry = next((item for item in reversed(history) if same_scope(item)), None)
    previous_snapshot = previous_entry.get("progress_snapshot") if isinstance(previous_entry, dict) else None
    comparison = compare_progress(previous_snapshot if isinstance(previous_snapshot, dict) else None, current_snapshot)
    current_signature = progress or _progress_signature(current_snapshot)
    previous_signature = str((previous_entry or {}).get("progress_signature") or "")
    # Callers may provide a richer project snapshot signature while the Run has
    # not yet persisted its effective project path. A changed external signature
    # is still concrete filesystem progress and must reset the soft loop guard.
    if progress and previous_signature and previous_signature != current_signature and comparison.get("state") in {"initial", "unchanged"}:
        comparison = {"state": "improved", "improved": True, "regressed": False, "reasons": ["external progress signature changed"], "regressions": []}
    entry = {
        "source_step": step_key,
        "step_key": step_key,
        "task_id": task,
        "retry_target": retry_target or step_key,
        "failure_class": failure_class,
        "fingerprint": fp,
        "message": text[:500],
        "progress_signature": current_signature,
        "progress_snapshot": current_snapshot,
        "progress_state": comparison.get("state"),
        "progress_reasons": list(comparison.get("reasons") or []),
        "progress_regressions": list(comparison.get("regressions") or []),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    history.append(entry)
    del history[:-200]

    # Only consecutive attempts with the same project/evidence signature count
    # as an unproductive loop. Any real filesystem/task/validation progress
    # resets the soft loop detector while cumulative safety budgets remain.
    same_count = 0
    no_file_count = 0
    for item in reversed(history):
        if not same_scope(item):
            continue
        if str(item.get("progress_signature") or "") != str(current_signature):
            break
        if item.get("fingerprint") == fp:
            same_count += 1
        if is_no_file_change_error(item.get("message") or ""):
            no_file_count += 1

    counters = run.setdefault("retry_budget_counters", {})
    counters["total"] = int(counters.get("total", 0) or 0) + 1
    step_counts = counters.setdefault("steps", {})
    task_counts = counters.setdefault("tasks", {})
    class_counts = counters.setdefault("classes", {})
    fingerprint_counts = counters.setdefault("fingerprints", {})
    no_file_counts = counters.setdefault("no_file_change", {})
    task_scope = f"{step_key}:{task or '-'}"
    class_scope = f"{task_scope}:{failure_class}"
    fingerprint_scope = f"{class_scope}:{fp}:{current_signature}"
    step_count = _increment(step_counts, step_key)
    task_count = _increment(task_counts, task_scope)
    class_count = _increment(class_counts, class_scope)
    fingerprint_count = _increment(fingerprint_counts, fingerprint_scope)
    no_file_total = _increment(no_file_counts, task_scope) if is_no_file_change_error(text) else int(no_file_counts.get(task_scope, 0) or 0)
    budget = recovery_budget(run, step_key)

    return {
        "schema": "aiwf.retry-guard-attempt.v3",
        "source_step": step_key,
        "step_key": step_key,
        "task_id": task,
        "retry_target": retry_target or step_key,
        "failure_class": failure_class,
        "fingerprint": fp,
        "same_failure_count": same_count,
        "no_file_change_count": no_file_count,
        "is_no_file_change": is_no_file_change_error(text),
        "run_failure_count": int(counters["total"]),
        "step_failure_count": step_count,
        "task_failure_count": task_count,
        "failure_class_count": class_count,
        "fingerprint_count": fingerprint_count,
        "no_file_change_total": no_file_total,
        "elapsed_minutes": round(_elapsed_minutes(run), 3),
        "progress_signature": current_signature,
        "progress_snapshot": current_snapshot,
        "progress_state": comparison.get("state"),
        "progress_reasons": list(comparison.get("reasons") or []),
        "progress_regressions": list(comparison.get("regressions") or []),
        "progress_detected": bool(comparison.get("improved")),
        "budget": budget,
    }


def should_stop_retry(
    run: dict[str, Any],
    *,
    step_key: str,
    error: BaseException | str,
    task_id: str | None = None,
    retry_target: str | None = None,
    progress: str | None = None,
) -> tuple[bool, str | None, dict[str, Any]]:
    attempt = record_failure_attempt(
        run,
        step_key=step_key,
        error=error,
        task_id=task_id,
        retry_target=retry_target,
        progress=progress,
    )
    budget = attempt["budget"]
    scope = step_key + (f"/{task_id}" if task_id else "")

    hard_checks = (
        (budget["wallClockMinutes"] and attempt["elapsed_minutes"] >= budget["wallClockMinutes"], f"wall-clock recovery budget reached ({attempt['elapsed_minutes']:.1f}/{budget['wallClockMinutes']} min)"),
        (budget["maxRunFailures"] and attempt["run_failure_count"] >= budget["maxRunFailures"], f"run failure budget reached ({attempt['run_failure_count']}/{budget['maxRunFailures']})"),
        (budget["maxStepFailures"] and attempt["step_failure_count"] >= budget["maxStepFailures"], f"step failure budget reached ({attempt['step_failure_count']}/{budget['maxStepFailures']})"),
        (budget["maxTaskFailures"] and attempt["task_failure_count"] >= budget["maxTaskFailures"], f"task failure budget reached ({attempt['task_failure_count']}/{budget['maxTaskFailures']})"),
        (not attempt["progress_detected"] and budget["maxFailureClass"] and attempt["failure_class_count"] >= budget["maxFailureClass"], f"failure-class budget reached ({attempt['failure_class_count']}/{budget['maxFailureClass']})"),
        (not attempt["progress_detected"] and budget["maxFingerprint"] and attempt["fingerprint_count"] >= budget["maxFingerprint"], f"same-fingerprint budget reached ({attempt['fingerprint_count']}/{budget['maxFingerprint']})"),
    )
    for reached, reason in hard_checks:
        if reached:
            attempt["hard_stop"] = True
            attempt["recovery_action"] = "stop"
            return True, f"Retry recovery budget stopped {scope}: {reason}.", attempt

    soft_reason: str | None = None
    if attempt["is_no_file_change"] and attempt["no_file_change_count"] >= NO_FILE_CHANGE_LIMIT:
        soft_reason = f"NO_FILE_CHANGE repeated {attempt['no_file_change_count']} times"
    elif attempt["same_failure_count"] >= DEFAULT_REPEATED_FAILURE_LIMIT:
        soft_reason = f"same failure repeated {attempt['same_failure_count']} times"
    elif budget["freshSessionEvery"] and attempt["failure_class_count"] % budget["freshSessionEvery"] == 0:
        soft_reason = f"failure class {attempt['failure_class']} repeated {attempt['failure_class_count']} times"

    if soft_reason:
        attempt["hard_stop"] = False
        attempt["recovery_action"] = "fresh_session"
        return True, f"Retry loop guard paused {scope}: {soft_reason}; rotate the agent session before continuing.", attempt
    attempt["hard_stop"] = False
    attempt["recovery_action"] = "retry"
    return False, None, attempt


def clear_retry_history(run: dict[str, Any], *, step_key: str, task_id: str | None = None) -> int:
    """Clear recent-loop fingerprints but preserve cumulative recovery budgets."""
    history = list(run.get("retry_guard_history") or [])
    task = str(task_id or "")
    kept = [
        item
        for item in history
        if not (
            (item.get("source_step") or item.get("step_key")) == step_key
            and (task_id is None or str(item.get("task_id") or "") == task)
        )
    ]
    run["retry_guard_history"] = kept
    return len(history) - len(kept)


__all__ = [
    "DEFAULT_REPEATED_FAILURE_LIMIT",
    "NO_FILE_CHANGE_LIMIT",
    "clear_retry_history",
    "failure_fingerprint",
    "is_no_file_change_error",
    "record_failure_attempt",
    "progress_signature",
    "recovery_budget",
    "should_stop_retry",
]
