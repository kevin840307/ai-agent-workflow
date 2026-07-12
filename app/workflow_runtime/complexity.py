from __future__ import annotations

from pathlib import Path
from typing import Any


def classify_workflow_complexity(
    requirement: str,
    project_dir: Path,
    *,
    explicit_profile: str | None = None,
    planned_task_count: int | None = None,
) -> dict[str, Any]:
    """Use structural metrics or explicit workflow metadata, never requirement keywords."""
    requested = str(explicit_profile or "").strip().lower()
    if requested and requested not in {"tiny", "standard", "complex"}:
        raise ValueError(f"Unsupported complexity profile: {explicit_profile}")
    file_count = 0
    total_bytes = 0
    try:
        for path in project_dir.rglob("*"):
            if path.is_file() and ".ai-workflow" not in path.parts and ".git" not in path.parts:
                file_count += 1
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    task_count = max(0, int(planned_task_count or 0))
    if requested:
        profile = requested
        source = "explicit"
    elif file_count > 300 or total_bytes > 50 * 1024 * 1024 or task_count > 5:
        profile = "complex"
        source = "project_metrics"
    elif file_count > 40 or total_bytes > 5 * 1024 * 1024 or task_count > 2:
        profile = "standard"
        source = "project_metrics"
    else:
        profile = "tiny"
        source = "project_metrics"
    settings = {
        "complex": {"max_tasks": 10, "recommended_tasks": "3-8"},
        "standard": {"max_tasks": 5, "recommended_tasks": "2-5"},
        "tiny": {"max_tasks": 2, "recommended_tasks": "1-2"},
    }[profile]
    return {"profile": profile, "source": source, "file_count": file_count, "total_bytes": total_bytes, "planned_task_count": task_count, **settings}


__all__ = ["classify_workflow_complexity"]
