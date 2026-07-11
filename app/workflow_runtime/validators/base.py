from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ValidatorPlan:
    id: str
    title: str
    command: list[str]
    detected_by: list[str] = field(default_factory=list)
    required: bool = True
    category: str = "test"


class ValidatorPlugin(Protocol):
    id: str
    title: str

    def detect(self, project: Path) -> bool: ...
    def plan(self, project: Path) -> ValidatorPlan: ...


__all__ = ["ValidatorPlan", "ValidatorPlugin"]
