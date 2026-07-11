from __future__ import annotations

from pathlib import Path
from typing import Any

_COMPLEX_MARKERS = (
    "multiple services", "cross-service", "migration", "architecture", "refactor entire",
    "database", "message queue", "kubernetes", "distributed", "security audit",
)
_STANDARD_MARKERS = (
    "tests", "api", "database", "config", "multiple files", "refactor", "integration",
)


def classify_workflow_complexity(requirement: str, project_dir: Path) -> dict[str, Any]:
    text = " ".join((requirement or "").lower().split())
    file_count = 0
    try:
        file_count = sum(
            1 for path in project_dir.rglob("*")
            if path.is_file() and ".ai-workflow" not in path.parts and ".git" not in path.parts
        )
    except OSError:
        file_count = 0
    if any(marker in text for marker in _COMPLEX_MARKERS) or file_count > 300 or len(text) > 1800:
        return {"profile": "complex", "max_tasks": 10, "recommended_tasks": "3-8"}
    if any(marker in text for marker in _STANDARD_MARKERS) or file_count > 40 or len(text) > 500:
        return {"profile": "standard", "max_tasks": 5, "recommended_tasks": "2-5"}
    return {"profile": "tiny", "max_tasks": 2, "recommended_tasks": "1-2"}
