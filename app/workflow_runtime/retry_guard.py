from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from .failure_classifier import classify_failure

DEFAULT_REPEATED_FAILURE_LIMIT = int(os.environ.get("AIWF_RETRY_REPEATED_FAILURE_LIMIT", "3") or 3)
NO_FILE_CHANGE_LIMIT = int(os.environ.get("AIWF_RETRY_NO_FILE_CHANGE_LIMIT", "2") or 2)


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


def record_failure_attempt(
    run: dict[str, Any],
    *,
    step_key: str,
    error: BaseException | str,
    task_id: str | None = None,
    retry_target: str | None = None,
) -> dict[str, Any]:
    text = str(error)
    fp = failure_fingerprint(text)
    failure_class = str(classify_failure(text, step_key=step_key).get("code") or "UNKNOWN")
    task = str(task_id or "")
    history = run.setdefault("retry_guard_history", [])
    entry = {
        "source_step": step_key,
        "step_key": step_key,  # backwards-compatible field
        "task_id": task,
        "retry_target": retry_target or step_key,
        "failure_class": failure_class,
        "fingerprint": fp,
        "message": text[:500],
    }
    history.append(entry)
    del history[:-50]

    def same_scope(item: dict[str, Any]) -> bool:
        return (
            (item.get("source_step") or item.get("step_key")) == step_key
            and str(item.get("task_id") or "") == task
            and str(item.get("failure_class") or failure_class) == failure_class
        )

    same_count = sum(1 for item in history if same_scope(item) and item.get("fingerprint") == fp)
    no_file_count = sum(1 for item in history if same_scope(item) and is_no_file_change_error(item.get("message") or ""))
    return {
        "schema": "aiwf.retry-guard-attempt.v2",
        "source_step": step_key,
        "step_key": step_key,
        "task_id": task,
        "retry_target": retry_target or step_key,
        "failure_class": failure_class,
        "fingerprint": fp,
        "same_failure_count": same_count,
        "no_file_change_count": no_file_count,
        "is_no_file_change": is_no_file_change_error(text),
    }


def should_stop_retry(
    run: dict[str, Any],
    *,
    step_key: str,
    error: BaseException | str,
    task_id: str | None = None,
    retry_target: str | None = None,
) -> tuple[bool, str | None, dict[str, Any]]:
    attempt = record_failure_attempt(
        run,
        step_key=step_key,
        error=error,
        task_id=task_id,
        retry_target=retry_target,
    )
    scope = step_key + (f"/{task_id}" if task_id else "")
    if attempt["is_no_file_change"] and attempt["no_file_change_count"] >= NO_FILE_CHANGE_LIMIT:
        return True, f"Retry loop guard stopped {scope}: NO_FILE_CHANGE repeated {attempt['no_file_change_count']} times.", attempt
    if attempt["same_failure_count"] >= DEFAULT_REPEATED_FAILURE_LIMIT:
        return True, f"Retry loop guard stopped {scope}: same failure repeated {attempt['same_failure_count']} times.", attempt
    return False, None, attempt


def clear_retry_history(run: dict[str, Any], *, step_key: str, task_id: str | None = None) -> int:
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
