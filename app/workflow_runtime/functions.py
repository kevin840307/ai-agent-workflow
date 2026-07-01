from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import ValidationError, WorkflowError
from app.core.paths import ROOT, read_text, write_text
from app.services.workflow_asset_service import run_python_asset
from app.workflow_functions import PYTHON_FUNCTIONS, WorkflowFunctionContext, WorkflowFunctionError

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowFunctionService:
    def __init__(self, *, log: LogFn, refresh_artifacts: RefreshArtifactsFn) -> None:
        self.log = log
        self.refresh_artifacts = refresh_artifacts

    def context(self, run: dict[str, Any], output_dir: Path | None = None) -> WorkflowFunctionContext:
        return WorkflowFunctionContext(
            run=run,
            output_dir=output_dir or Path(run["workspace"]) / "output",
            project_dir=Path(run.get("project_path") or ROOT),
            root_dir=ROOT,
            read_text=read_text,
            write_text=write_text,
            log=self.log,
            refresh_artifacts=self.refresh_artifacts,
        )

    def validate_spec(self, output_dir: Path) -> None:
        try:
            ctx = self.context({"workspace": str(output_dir.parent), "project_path": str(ROOT), "id": ""}, output_dir)
            PYTHON_FUNCTIONS["validate_spec"](ctx)
        except WorkflowFunctionError as exc:
            raise ValidationError(str(exc)) from exc

    def validate_todo(self, output_dir: Path) -> None:
        try:
            ctx = self.context({"workspace": str(output_dir.parent), "project_path": str(ROOT), "id": ""}, output_dir)
            PYTHON_FUNCTIONS["validate_todo"](ctx)
        except WorkflowFunctionError as exc:
            raise ValidationError(str(exc)) from exc

    def require_status(self, path: Path, expected: str) -> None:
        if expected != "PASS":
            text = read_text(path)
            if f"Status: {expected}" not in text:
                raise ValidationError(f"{path.name} must contain 'Status: {expected}'.")
            return
        try:
            ctx = self.context({"workspace": str(path.parent.parent), "project_path": str(ROOT), "id": ""}, path.parent)
            PYTHON_FUNCTIONS["require_status_pass"](ctx, path.name)
        except WorkflowFunctionError as exc:
            raise ValidationError(str(exc)) from exc

    async def call_python_function(
        self,
        run: dict[str, Any],
        function_id: str,
        output_dir: Path,
        artifact: str | None = None,
    ) -> None:
        function = PYTHON_FUNCTIONS.get(function_id)
        if not function:
            normalized = str(function_id or "").replace("\\", "/")
            if normalized.startswith(".ai-workflow/"):
                normalized = normalized[len(".ai-workflow/") :]
            if normalized.startswith(("validators/", "tools/")) and normalized.endswith(".py"):
                try:
                    await run_python_asset(run, normalized, output_dir, artifact)
                    return
                except Exception as exc:
                    raise WorkflowError(str(exc)) from exc
            raise WorkflowError(f"Unknown workflow Python function: {function_id}")
        try:
            ctx = self.context(run, output_dir)
            result = function(ctx, artifact) if artifact else function(ctx)
            if asyncio.iscoroutine(result):
                await result
        except WorkflowFunctionError as exc:
            raise WorkflowError(str(exc)) from exc
