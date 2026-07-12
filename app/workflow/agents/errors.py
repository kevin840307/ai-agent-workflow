from __future__ import annotations

from typing import Any


_ERROR_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SESSION_NOT_FOUND", ("no saved session found", "session not found", "unknown session", "invalid session", "could not find session")),
    ("SESSION_ALREADY_EXISTS", ("session id", "already exists")),
    ("CONTEXT_LIMIT_REACHED", ("context is too large", "context limit", "maximum context", "compression status: noop")),
    ("AGENT_TIMEOUT", ("timed out", "timeout")),
    ("AUTHENTICATION_FAILED", ("incorrect api key", "unauthorized", "authentication failed", "401")),
    ("RATE_LIMITED", ("rate limit", "too many requests", "429")),
    ("EMPTY_OUTPUT", ("returned empty output", "returned empty stdout")),
    (
        "TRANSIENT_API_FAILURE",
        (
            "connection reset",
            "connection refused",
            "econnrefused",
            "actively refused",
            "failed to connect",
            "connectex",
            "econnreset",
            "socket hang up",
            "connection closed",
            "connection aborted",
            "temporarily unavailable",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "fetch failed",
            "network error",
            "http 502",
            "http 503",
            "http 504",
        ),
    ),
)


def classify_agent_error(error: Any) -> dict[str, Any]:
    message = str(error or "").strip()
    lowered = message.lower()
    for code, patterns in _ERROR_PATTERNS:
        if code == "SESSION_ALREADY_EXISTS":
            if all(pattern in lowered for pattern in patterns):
                return {"code": code, "message": message, "recoverable": True, "strategy": "resume"}
            continue
        if any(pattern in lowered for pattern in patterns):
            strategy = {
                "SESSION_NOT_FOUND": "create",
                "CONTEXT_LIMIT_REACHED": "handoff_fresh_session",
                "AGENT_TIMEOUT": "fresh_session",
                "RATE_LIMITED": "backoff",
                "TRANSIENT_API_FAILURE": "backoff",
                "EMPTY_OUTPUT": "retry",
            }.get(code, "stop")
            return {"code": code, "message": message, "recoverable": code not in {"AUTHENTICATION_FAILED"}, "strategy": strategy}
    return {"code": "AGENT_ERROR", "message": message, "recoverable": False, "strategy": "inspect"}


__all__ = ["classify_agent_error"]
