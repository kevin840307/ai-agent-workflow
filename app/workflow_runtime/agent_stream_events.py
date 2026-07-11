from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


_TOOL_MARKERS = (
    "tool_use",
    "tool_call",
    "tool_result",
    "tool_output",
    "function_call",
    "function_result",
    "command_output",
    "file_operation",
)


@dataclass(slots=True)
class AgentJsonStreamParser:
    """Normalize Qwen/OpenCode JSONL without treating tool transcripts as final output.

    Tool activity is surfaced as ``status`` for the live UI, partial assistant text is
    streamed as ``display``, and only assistant/final text is retained as the step
    artifact.  This prevents successful write-tool results such as
    ``Successfully created ...`` from becoming a workflow error body.
    """

    final_parts: list[str] = field(default_factory=list)
    partial_text: str = ""
    _seen_status: set[str] = field(default_factory=set)

    def feed_line(self, line: str) -> list[tuple[str, str]]:
        raw = line.strip()
        if not raw:
            return []
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            # Plain text from a provider is treated as assistant text for backwards
            # compatibility. Provider stderr never reaches this parser.
            self._set_final(line)
            return [("display", line)]
        if not isinstance(event, dict):
            return []

        kind = self._event_kind(event)
        text = self._event_text(event)
        if not text:
            return []

        if kind == "tool":
            normalized = self._status_text(text)
            if not normalized or normalized in self._seen_status:
                return []
            self._seen_status.add(normalized)
            return [("status", normalized)]
        if kind == "partial":
            delta = self._partial_delta(text)
            return [("display", delta)] if delta else []
        if kind == "thinking":
            return [("thinking", text)]
        if kind == "ignore":
            return []

        normalized = text.strip()
        current_final = "".join(self.final_parts).strip()
        if normalized and normalized in {self.partial_text.strip(), current_final}:
            if not self.final_parts:
                self._set_final(text)
            return []
        self._set_final(text)
        return [("display", text)]

    def final_text(self, fallback: str = "") -> str:
        text = "".join(self.final_parts).strip()
        if text:
            return text
        if self.partial_text.strip():
            return self.partial_text.strip()
        return fallback.strip()

    def _set_final(self, text: str) -> None:
        # A provider's final event normally contains the complete answer. Replace
        # partial/final fragments instead of concatenating tool transcripts or
        # duplicate result events.
        self.final_parts[:] = [text]

    def _partial_delta(self, text: str) -> str:
        if text.startswith(self.partial_text):
            delta = text[len(self.partial_text) :]
        else:
            delta = text
        self.partial_text = text
        return delta

    def _event_kind(self, event: dict[str, Any]) -> str:
        label = self._label_text(event)
        role = self._event_role(event)
        if role in {"tool", "function"} or any(token in label for token in _TOOL_MARKERS):
            return "tool"
        if any(token in label for token in ["thinking", "reasoning", "thought"]):
            return "thinking"
        if any(token in label for token in ["partial", "delta", "chunk", "content_block_delta", "text_delta"]):
            return "partial"
        if role in {"user", "system"}:
            return "ignore"
        # Qwen's top-level result event and OpenCode's text event are final
        # assistant output even when no explicit role is present.
        if role in {"assistant", "model", ""}:
            return "final"
        return "ignore"

    def _event_role(self, event: dict[str, Any]) -> str:
        candidates: list[Any] = [event.get("role")]
        for key in ("message", "event", "part", "delta"):
            nested = event.get(key)
            if isinstance(nested, dict):
                candidates.append(nested.get("role"))
                message = nested.get("message")
                if isinstance(message, dict):
                    candidates.append(message.get("role"))
        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if value:
                return value
        return ""

    def _label_text(self, value: Any) -> str:
        if isinstance(value, dict):
            parts = [str(value.get(key) or "") for key in ["type", "event", "kind", "role", "category", "name"]]
            for key in ["event", "part", "delta", "message", "content"]:
                nested = value.get(key)
                if isinstance(nested, dict):
                    parts.append(self._label_text(nested))
                elif isinstance(nested, list):
                    parts.extend(self._label_text(item) for item in nested if isinstance(item, dict))
            return " ".join(parts).lower()
        return ""

    def _event_text(self, event: dict[str, Any]) -> str:
        for key in ["delta", "text", "content", "message", "output", "result", "response", "part", "event"]:
            text = self._coerce_text(event.get(key))
            if text:
                return text
        for key in ["thinking", "reasoning", "thought"]:
            text = self._coerce_text(event.get(key))
            if text:
                return text
        return ""

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(self._coerce_text(item) for item in value)
        if isinstance(value, dict):
            for key in ["text", "content", "message", "value", "delta", "part", "event", "result", "response", "output"]:
                text = self._coerce_text(value.get(key))
                if text:
                    return text
            if value.get("type") in {"text", "thinking", "reasoning"}:
                return self._coerce_text(value.get("data"))
        return ""

    @staticmethod
    def _status_text(text: str) -> str:
        compact = " ".join((text or "").strip().split())
        return compact[:500]
