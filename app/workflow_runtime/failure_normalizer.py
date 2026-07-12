from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.paths import utc_now
from .failure_classifier import classify_failure


def _safe_text(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _evidence_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def normalize_failure(
    error: BaseException | str | None,
    *,
    source: str,
    step_key: str | None = None,
    error_code: str | None = None,
    owner_task_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a non-empty, stable failure envelope for retry/UI/reporting.

    Recovery must never receive an empty message.  The classifier remains the
    source of retry semantics while this envelope carries source/evidence and a
    deterministic fingerprint shared by runtime, artifacts, and UI.
    """
    raw = _safe_text(error)
    exception_type = type(error).__name__ if isinstance(error, BaseException) else None
    fallback = f"{source} failed"
    if exception_type:
        fallback += f" with {exception_type}"
    summary = raw or fallback
    failure = classify_failure(summary, step_key=step_key, error_code=error_code)
    code = str(failure.get("code") or error_code or "UNKNOWN")
    payload = {
        "source": source,
        "step_key": step_key,
        "owner_task_id": owner_task_id,
        "code": code,
        "summary": summary[:4000],
        "exception_type": exception_type,
        "evidence": dict(evidence or {}),
    }
    return {
        "schema": "aiwf.failure.v2",
        "code": code,
        "title": str(failure.get("title") or code.replace("_", " ").title()),
        "summary": payload["summary"],
        "source": source,
        "step_key": step_key,
        "owner_task_id": owner_task_id,
        "retryable": bool(failure.get("retryable", failure.get("auto_repairable", True))),
        "auto_repairable": bool(failure.get("auto_repairable", True)),
        "severity": str(failure.get("severity") or "medium"),
        "recommended_action": str(failure.get("recommended_action") or failure.get("repair_instruction") or "Inspect evidence and retry the owning step."),
        "exception_type": exception_type,
        "evidence": payload["evidence"],
        "evidence_hash": _evidence_hash(payload),
        "occurred_at": utc_now(),
    }


__all__ = ["normalize_failure"]
