from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from app.runtime_modules.errors import WorkflowError

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
            "expected file(s) not found",
            "no_file_change",
        ]
    )


def record_failure_attempt(run: dict[str, Any], *, step_key: str, error: BaseException | str) -> dict[str, Any]:
    text = str(error)
    fp = failure_fingerprint(text)
    history = run.setdefault("retry_guard_history", [])
    entry = {"step_key": step_key, "fingerprint": fp, "message": text[:500]}
    history.append(entry)
    # Keep run state compact in long local sessions.
    del history[:-50]
    same_count = sum(1 for item in history if item.get("step_key") == step_key and item.get("fingerprint") == fp)
    no_file_count = sum(1 for item in history if item.get("step_key") == step_key and is_no_file_change_error(item.get("message") or ""))
    return {
        "schema": "aiwf.retry-guard-attempt.v1",
        "step_key": step_key,
        "fingerprint": fp,
        "same_failure_count": same_count,
        "no_file_change_count": no_file_count,
        "is_no_file_change": is_no_file_change_error(text),
    }


def should_stop_retry(run: dict[str, Any], *, step_key: str, error: BaseException | str) -> tuple[bool, str | None, dict[str, Any]]:
    attempt = record_failure_attempt(run, step_key=step_key, error=error)
    if attempt["is_no_file_change"] and attempt["no_file_change_count"] >= NO_FILE_CHANGE_LIMIT:
        return True, f"Retry loop guard stopped {step_key}: NO_FILE_CHANGE repeated {attempt['no_file_change_count']} times.", attempt
    if attempt["same_failure_count"] >= DEFAULT_REPEATED_FAILURE_LIMIT:
        return True, f"Retry loop guard stopped {step_key}: same failure repeated {attempt['same_failure_count']} times.", attempt
    return False, None, attempt
