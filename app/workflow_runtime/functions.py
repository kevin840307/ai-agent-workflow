from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import ValidationError, WorkflowError
from app.core.paths import ROOT, read_text, write_text
from app.security.workspace_guard import guarded_write_text, is_within
from app.services.workflow_asset_service import resolve_function_reference, run_python_asset
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowFunctionService:
    def __init__(self, *, log: LogFn, refresh_artifacts: RefreshArtifactsFn) -> None:
        self.log = log
        self.refresh_artifacts = refresh_artifacts

    def context(self, run: dict[str, Any], output_dir: Path | None = None) -> WorkflowFunctionContext:
        project_dir = Path(run.get("project_path") or ROOT).expanduser().resolve()

        workspace_root = Path(run.get("workspace") or (output_dir or Path()).parent).expanduser().resolve()

        def project_scoped_write(path: Path, content: str) -> None:
            target = Path(path).expanduser().resolve()
            if is_within(workspace_root, target):
                write_text(target, content)
                return
            guarded_write_text(project_dir, target, content, write_text)

        return WorkflowFunctionContext(
            run=run,
            output_dir=output_dir or Path(run["workspace"]) / "output",
            project_dir=project_dir,
            root_dir=ROOT,
            read_text=read_text,
            write_text=project_scoped_write,
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
        function_id = str(function_id or "").strip()
        if not function_id:
            raise WorkflowError("Python function is required")

        function = PYTHON_FUNCTIONS.get(function_id)
        if function:
            try:
                ctx = self.context(run, output_dir)
                signature = inspect.signature(function)
                result = function(ctx, artifact) if artifact and len(signature.parameters) >= 2 else function(ctx)
                if asyncio.iscoroutine(result):
                    await result
                return
            except WorkflowFunctionError as exc:
                message = str(exc).strip() or f"{function_id} failed with {type(exc).__name__}"
                raise WorkflowError(message) from exc

        function_path = resolve_function_reference(function_id, str(run.get("project_path") or ROOT))
        if not function_path:
            raise WorkflowError(f"Unknown workflow Python function: {function_id}")
        try:
            await run_python_asset(run, function_path, output_dir, artifact)
        except Exception as exc:
            message = str(exc).strip() or f"{function_id} failed with {type(exc).__name__}"
            raise WorkflowError(message) from exc

    async def call_python_functions(
        self,
        run: dict[str, Any],
        function_ids: list[str],
        output_dir: Path,
        artifact: str | None = None,
    ) -> None:
        ordered = [str(item or "").strip() for item in function_ids if str(item or "").strip()]
        if not ordered:
            raise WorkflowError("At least one Python function is required")
        for index, function_id in enumerate(ordered, start=1):
            await self.log(run, f"python function {index}/{len(ordered)}: {function_id}")
            await self.call_python_function(run, function_id, output_dir, artifact)
