from __future__ import annotations

import json
import re
from typing import Any


def json_with_triple_quoted_strings(text: str) -> str:
    """Convert common model-emitted triple-quoted JSON values into valid JSON."""

    def replace(match: re.Match[str]) -> str:
        return match.group(1) + json.dumps(match.group(2))

    return re.sub(r'(:\s*)"""(.*?)"""', replace, text, flags=re.DOTALL)


def tool_call_payload(output: str) -> Any:
    """Parse a standalone tool-call payload without executing it."""
    text = (output or "").strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        relaxed = json_with_triple_quoted_strings(text)
        if relaxed == text:
            return None
        try:
            return json.loads(relaxed)
        except json.JSONDecodeError:
            return None


def tool_call_name(output: str) -> str:
    """Return the declared tool name from model output, if present."""
    text = (output or "").strip()
    if not text:
        return ""
    parsed = tool_call_payload(text)
    if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
        return parsed["name"].strip()
    match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
    return match.group(1).strip() if match else ""


__all__ = ["json_with_triple_quoted_strings", "tool_call_payload", "tool_call_name"]
