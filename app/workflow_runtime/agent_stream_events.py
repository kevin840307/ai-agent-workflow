from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentJsonStreamParser:
    """Best-effort parser for provider JSONL streams."""

    final_parts: list[str] = field(default_factory=list)
    partial_text: str = ""

    def feed_line(self, line: str) -> list[tuple[str, str]]:
        raw = line.strip()
        if not raw:
            return []
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return [("display", line)]
        if not isinstance(event, dict):
            return []

        kind = self._event_kind(event)
        text = self._event_text(event)
        if not text:
            return []

        if kind == "partial":
            delta = self._partial_delta(text)
            return [("display", delta)] if delta else []
        if kind == "thinking":
            return [("thinking", text)]

        normalized = text.strip()
        current_final = "".join(self.final_parts).strip()
        if normalized and normalized in {self.partial_text.strip(), current_final}:
            if not self.final_parts:
                self.final_parts.append(text)
            return []
        if self.partial_text and normalized == self.partial_text.strip() and not self.final_parts:
            self.final_parts.append(text)
            return []
        self.final_parts.append(text)
        return [("display", text)]

    def final_text(self, fallback: str = "") -> str:
        text = "".join(self.final_parts).strip()
        if text:
            return text
        if self.partial_text.strip():
            return self.partial_text.strip()
        return fallback.strip()

    def _partial_delta(self, text: str) -> str:
        if text.startswith(self.partial_text):
            delta = text[len(self.partial_text) :]
        else:
            delta = text
        self.partial_text = text
        return delta

    def _event_kind(self, event: dict[str, Any]) -> str:
        label = self._label_text(event)
        if any(token in label for token in ["thinking", "reasoning", "thought"]):
            return "thinking"
        if any(token in label for token in ["partial", "delta", "chunk"]):
            return "partial"
        return "final"

    def _label_text(self, value: Any) -> str:
        if isinstance(value, dict):
            parts = [
                str(value.get(key) or "")
                for key in ["type", "event", "kind", "role", "category"]
            ]
            for key in ["event", "part", "delta", "message"]:
                nested = value.get(key)
                if isinstance(nested, dict):
                    parts.append(self._label_text(nested))
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
            for key in ["text", "content", "message", "value", "delta", "part", "event", "result", "response"]:
                text = self._coerce_text(value.get(key))
                if text:
                    return text
            if value.get("type") in {"text", "thinking", "reasoning"}:
                return self._coerce_text(value.get("data"))
        return ""
