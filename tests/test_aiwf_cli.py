from __future__ import annotations

import asyncio
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
                        "--agent",
                        "opencode",
                        "--thinking-level",
                        "high",
                        "--validation-script",
                        "tools/check_config.py",
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
            self.assertEqual(body.agent, "opencode")
            self.assertEqual(body.thinking_level, "high")
            self.assertEqual(body.validation_script, "tools/check_config.py")

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

    async def test_cli_accepts_auto_shortcut_command_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = {"id": "session-shortcut", "project_path": str(project)}
            created_run = {
                "id": "run-shortcut",
                "session_id": "session-shortcut",
                "status": "queued",
                "project_path": str(project),
            }
            with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)), patch.object(
                aiwf.workflow_service,
                "create_workflow_run",
                new=AsyncMock(return_value=created_run),
            ) as create_run:
                with redirect_stdout(StringIO()):
                    code = await aiwf.run_cli([
                        str(project),
                        "--engine",
                        "auto",
                        "--user",
                        "製作 config 驗證小工具",
                        "--workflow",
                        "general-auto-development",
                        "--validation-script",
                        "tools/check_config.py",
                    ])

            self.assertEqual(code, 0)
            _, body = create_run.await_args.args
            self.assertEqual(body.requirement, "製作 config 驗證小工具")
            self.assertEqual(body.project_path, str(project))
            self.assertEqual(body.workflow_id, "general-auto-development")
            self.assertEqual(body.validation_script, "tools/check_config.py")

    async def test_cli_auto_shortcut_defaults_target_to_current_directory(self) -> None:
        session = {"id": "session-default-target", "project_path": "."}
        created_run = {
            "id": "run-default-target",
            "session_id": "session-default-target",
            "status": "queued",
            "project_path": ".",
        }
        with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)), patch.object(
            aiwf.workflow_service,
            "create_workflow_run",
            new=AsyncMock(return_value=created_run),
        ) as create_run:
            with redirect_stdout(StringIO()):
                code = await aiwf.run_cli([
                    "--engine",
                    "auto",
                    "--user",
                    "build a config validation tool",
                    "--workflow",
                    "general-auto-development",
                ])

        self.assertEqual(code, 0)
        _, body = create_run.await_args.args
        self.assertEqual(body.project_path, ".")
        self.assertEqual(body.requirement, "build a config validation tool")

    async def test_cli_workflow_shortcut_uses_workflow_then_requirement(self) -> None:
        session = {"id": "session-workflow-shortcut", "project_path": "."}
        created_run = {
            "id": "run-workflow-shortcut",
            "session_id": "session-workflow-shortcut",
            "status": "queued",
            "project_path": ".",
        }
        with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)), patch.object(
            aiwf.workflow_service,
            "create_workflow_run",
            new=AsyncMock(return_value=created_run),
        ) as create_run:
            with redirect_stdout(StringIO()):
                code = await aiwf.run_cli(["wf", "general-auto-development", "add quick sort"])

        self.assertEqual(code, 0)
        _, body = create_run.await_args.args
        self.assertEqual(body.project_path, ".")
        self.assertEqual(body.workflow_id, "general-auto-development")
        self.assertEqual(body.requirement, "add quick sort")
        self.assertIsNone(body.skill)
        self.assertIsNone(body.config)

    async def test_cli_shortcut_accepts_skill_and_config_positionals(self) -> None:
        session = {"id": "session-skill-config", "project_path": "."}
        created_run = {
            "id": "run-skill-config",
            "session_id": "session-skill-config",
            "status": "queued",
            "project_path": ".",
        }
        with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)), patch.object(
            aiwf.workflow_service,
            "create_workflow_run",
            new=AsyncMock(return_value=created_run),
        ) as create_run:
            with redirect_stdout(StringIO()):
                code = await aiwf.run_cli([
                    "wstep",
                    "custom_build.md",
                    "build.yaml",
                    "add quick sort",
                ])

        self.assertEqual(code, 0)
        _, body = create_run.await_args.args
        self.assertEqual(body.project_path, ".")
        self.assertEqual(body.skill, "custom_build.md")
        self.assertEqual(body.config, "build.yaml")
        self.assertIsNone(body.workflow_id)
        self.assertEqual(body.requirement, "add quick sort")

    async def test_cli_shortcut_accepts_agent_slash_command_and_config(self) -> None:
        session = {"id": "session-slash-config", "project_path": "."}
        created_run = {
            "id": "run-slash-config",
            "session_id": "session-slash-config",
            "status": "queued",
            "project_path": ".",
        }
        with patch.object(aiwf, "_init_runtime", new=AsyncMock()), patch.object(aiwf, "create_project", new=AsyncMock(return_value=session)), patch.object(
            aiwf.workflow_service,
            "create_workflow_run",
            new=AsyncMock(return_value=created_run),
        ) as create_run:
            with redirect_stdout(StringIO()):
                code = await aiwf.run_cli([
                    "wstep",
                    "/build",
                    "build.yaml",
                    "implement config crud",
                ])

        self.assertEqual(code, 0)
        _, body = create_run.await_args.args
        self.assertEqual(body.skill, "/build")
        self.assertEqual(body.config, "build.yaml")
        self.assertEqual(body.requirement, "implement config crud")

    async def test_wait_for_run_awaits_local_workflow_task(self) -> None:
        observed: list[str] = []

        async def complete_task() -> None:
            observed.append("task")

        task = asyncio.create_task(complete_task())
        aiwf.runtime.running_tasks["run-local-task"] = task
        try:
            with patch.object(
                aiwf.workflow_service,
                "get_run",
                new=AsyncMock(return_value={"id": "run-local-task", "status": "done"}),
            ) as get_run:
                run = await aiwf._wait_for_run("run-local-task")
        finally:
            aiwf.runtime.running_tasks.pop("run-local-task", None)

        self.assertEqual(run["status"], "done")
        self.assertEqual(observed, ["task"])
        get_run.assert_awaited_once_with("run-local-task")


if __name__ == "__main__":
    unittest.main()
