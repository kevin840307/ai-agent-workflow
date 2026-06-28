from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


class WorkflowFunctionError(Exception):
    pass


@dataclass(frozen=True)
class WorkflowFunctionContext:
    run: dict[str, Any]
    output_dir: Path
    project_dir: Path
    root_dir: Path
    read_text: Callable[[Path], str]
    write_text: Callable[[Path, str], None]
    log: Callable[[dict[str, Any], str], Awaitable[None]]
    refresh_artifacts: Callable[[str], Awaitable[None]]
