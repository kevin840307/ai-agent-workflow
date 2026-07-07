from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WorkflowExecutionContext:
    run_id: str
    workflow_id: str
    workspace: Path
    project_path: Path
    start_index: int = 0
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_run(cls, run: dict[str, Any], *, start_index: int = 0) -> "WorkflowExecutionContext":
        return cls(
            run_id=str(run.get("id") or ""),
            workflow_id=str(run.get("workflow_id") or ""),
            workspace=Path(run.get("workspace") or "."),
            project_path=Path(run.get("project_path") or run.get("workspace") or "."),
            start_index=start_index,
            metadata=dict(run.get("metadata") or {}),
        )
