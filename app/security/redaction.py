from __future__ import annotations

import re
from typing import Any

_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*)['\"]?[^\s,'\";]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(OPENAI_API_KEY|OPENROUTER_API_KEY|ANTHROPIC_API_KEY|QWEN_API_KEY|GEMINI_API_KEY)=([^\s]+)"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"), r"\1[REDACTED]\2"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
)


def redact_text(value: Any) -> str:
    text = "" if value is None else str(value)
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


__all__ = ["redact_text", "redact_value"]
