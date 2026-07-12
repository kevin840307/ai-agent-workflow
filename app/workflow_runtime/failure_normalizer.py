from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from app.core.paths import utc_now
from .failure_classifier import canonical_failure_code, classify_failure


def _safe_text(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("summary", "message", "error", "detail", "raw_message"):
            if value.get(key):
                return str(value[key]).strip()
    return str(value or "").strip()


def _evidence_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


def _structured_code(error: Any, error_code: str | None) -> str | None:
    code = canonical_failure_code(error_code)
    if code:
        return code
    if isinstance(error, Mapping):
        nested = error.get("failure") if isinstance(error.get("failure"), Mapping) else error
        for key in ("code", "error_code", "failure_code"):
            code = canonical_failure_code(nested.get(key))
            if code:
                return code
    if isinstance(error, BaseException):
        for key in ("failure_code", "error_code", "code"):
            code = canonical_failure_code(getattr(error, key, None))
            if code:
                return code
    return None


def normalize_failure(
    error: BaseException | str | Mapping[str, Any] | None,
    *,
    source: str,
    step_key: str | None = None,
    error_code: str | None = None,
    owner_task_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Return the V3 failure envelope shared by runtime, retry, UI, and reports.

    Producers should provide a deterministic ``error_code``. Raw text remains
    available for diagnostics, but is only classified as a compatibility
    fallback when a provider cannot emit a structured code.
    """
    raw = _safe_text(error)
    exception_type = type(error).__name__ if isinstance(error, BaseException) else None
    fallback = f"{source} failed" + (f" with {exception_type}" if exception_type else "")
    summary = raw or fallback
    explicit_code = canonical_failure_code(error_code)
    structured_code = _structured_code(error, error_code)
    failure = classify_failure(error or summary, step_key=step_key, error_code=structured_code or error_code)
    code = str(failure.get("code") or structured_code or "UNKNOWN")
    evidence_payload = dict(evidence or {})
    payload = {
        "source": source,
        "provider": provider,
        "step_key": step_key,
        "owner_task_id": owner_task_id,
        "code": code,
        "summary": summary[:4000],
        "exception_type": exception_type,
        "evidence": evidence_payload,
        "evidence_refs": list(evidence_refs or []),
    }
    return {
        "schema": "aiwf.failure.v3",
        "schema_version": 3,
        "compatible_with": ["aiwf.failure.v2"],
        "code": code,
        "title": str(failure.get("title") or code.replace("_", " ").title()),
        "summary": payload["summary"],
        "raw_message": raw[:16000],
        "source": source,
        "provider": provider,
        "classification_source": "error_code" if explicit_code else ("structured" if structured_code else str(failure.get("classification_source") or "text_fallback")),
        "step_key": step_key,
        "owner_task_id": owner_task_id,
        "retryable": bool(failure.get("retryable", failure.get("auto_repairable", False))),
        "auto_repairable": bool(failure.get("auto_repairable", False)),
        "retry_target": str(failure.get("retry_target") or "manual inspection"),
        "severity": str(failure.get("severity") or "medium"),
        "recommended_action": str(failure.get("recommended_action") or failure.get("repair_prompt_hint") or "Inspect evidence and retry the owning step."),
        "exception_type": exception_type,
        "evidence": evidence_payload,
        "evidence_refs": payload["evidence_refs"],
        "evidence_hash": _evidence_hash(payload),
        "occurred_at": utc_now(),
    }


__all__ = ["normalize_failure"]
