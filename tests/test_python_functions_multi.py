from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.services import workflow_asset_service
from app.workflow_runtime.functions import WorkflowFunctionService
from app.workflow_runtime.step_utils import parse_function_refs, step_function_names


class PythonFunctionsMultiTests(unittest.TestCase):
    def test_parse_function_refs_accepts_list_comma_and_newline(self) -> None:
        self.assertEqual(
            parse_function_refs(["validate_spec, functions/a.py", "run_pytest\nfunctions/a.py"]),
            ["validate_spec", "functions/a.py", "run_pytest"],
        )

    def test_step_function_names_prefers_ordered_functions(self) -> None:
        step = {"config": {"functions": ["functions/a.py", "run_pytest"], "function": "validate_spec"}}
        self.assertEqual(step_function_names(step), ["functions/a.py", "run_pytest", "validate_spec"])

    def test_call_python_functions_runs_in_configured_order(self) -> None:
        asyncio.run(self._run_order_case())

    async def _run_order_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            output = workspace / "output"
            project = root / "project"
            output.mkdir(parents=True)
            project.mkdir()

            original_root = workflow_asset_service.GLOBAL_ASSET_ROOT
            workflow_asset_service.GLOBAL_ASSET_ROOT = root / "ai-workflow"
            try:
                workflow_asset_service.ensure_asset_dirs(str(project))
                workflow_asset_service.write_asset(
                    "functions/first.py",
                    "def run(context, artifact=None):\n"
                    "    path = context.output_dir / 'order.txt'\n"
                    "    existing = path.read_text(encoding='utf-8') if path.exists() else ''\n"
                    "    context.write_text(path, existing + 'first\\n')\n",
                    scope="global",
                )
                workflow_asset_service.write_asset(
                    "functions/second.py",
                    "def run(context, artifact=None):\n"
                    "    path = context.output_dir / 'order.txt'\n"
                    "    existing = path.read_text(encoding='utf-8') if path.exists() else ''\n"
                    "    context.write_text(path, existing + 'second\\n')\n",
                    scope="global",
                )
                logs: list[str] = []
                service = WorkflowFunctionService(
                    log=lambda run, message: _append(logs, message),
                    refresh_artifacts=lambda run_id: _noop(),
                )
                run = {"id": "run-1", "workspace": str(workspace), "project_path": str(project)}

                await service.call_python_functions(run, ["functions/first.py", "functions/second.py"], output)

                self.assertEqual((output / "order.txt").read_text(encoding="utf-8"), "first\nsecond\n")
                self.assertEqual(logs, [
                    "python function 1/2: functions/first.py",
                    "python function 2/2: functions/second.py",
                ])
            finally:
                workflow_asset_service.GLOBAL_ASSET_ROOT = original_root


async def _append(target: list[str], message: str) -> None:
    target.append(message)


async def _noop() -> None:
    return None


if __name__ == "__main__":
    unittest.main()
