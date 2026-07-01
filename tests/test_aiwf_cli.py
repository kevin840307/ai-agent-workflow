from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.cli import aiwf
from app.services import workflow_asset_service


class AiWorkflowCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_run_uses_same_workflow_service_as_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = {"id": "session-cli", "project_path": str(project)}
            created_run = {
                "id": "run-cli",
                "session_id": "session-cli",
                "status": "queued",
                "project_path": str(project),
            }
            with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)) as create_project, patch.object(
                aiwf.workflow_service,
                "create_workflow_run",
                new=AsyncMock(return_value=created_run),
            ) as create_run:
                with redirect_stdout(StringIO()):
                    code = await aiwf.run_cli([
                        "run",
                        "build a sorter",
                        "--project",
                        str(project),
                        "--workflow",
                        "custom-workflow",
                        "--title",
                        "CLI Title",
                    ])

            self.assertEqual(code, 0)
            create_project.assert_awaited_once()
            create_run.assert_awaited_once()
            session_id, body = create_run.await_args.args
            self.assertEqual(session_id, "session-cli")
            self.assertEqual(body.requirement, "build a sorter")
            self.assertEqual(body.project_path, str(project))
            self.assertEqual(body.workflow_id, "custom-workflow")

    async def test_cli_assets_uses_shared_asset_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_global = workflow_asset_service.GLOBAL_ASSET_ROOT
            workflow_asset_service.GLOBAL_ASSET_ROOT = Path(tmp) / "global"
            try:
                workflow_asset_service.write_asset("steps/cli.md", "CLI skill", scope="global")
                with patch.object(aiwf, "_init_runtime", new=AsyncMock()), redirect_stdout(StringIO()):
                    code = await aiwf.run_cli(["assets"])
                self.assertEqual(code, 0)
            finally:
                workflow_asset_service.GLOBAL_ASSET_ROOT = original_global


if __name__ == "__main__":
    unittest.main()
