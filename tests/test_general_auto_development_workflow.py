from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.errors import WorkflowError
from app.services import workflow_asset_service
from app.workflow_runtime.functions import WorkflowFunctionService


async def _noop_log(_run: dict, _message: str) -> None:
    return None


async def _noop_refresh(_run_id: str) -> None:
    return None


class GeneralAutoDevelopmentWorkflowTests(unittest.TestCase):
    def test_workflow_loads_with_mandatory_external_validation_retrying_build(self) -> None:
        workflow = workflow_asset_service.load_workflow_asset("general-auto-development")

        keys = [step["key"] for step in workflow["steps"]]
        self.assertLessEqual(len(keys), 16)
        self.assertEqual(
            keys,
            [
                "prepare_project",
                "plan_tasks",
                "implementation_review",
                "build",
                "run_external_validation",
                "final_review",
                "final_gate",
            ],
        )

        validation = next(step for step in workflow["steps"] if step["key"] == "run_external_validation")
        self.assertEqual(validation["type"], "python")
        self.assertEqual(validation["function"], "run_external_validation")
        self.assertEqual(validation["retryFromStepKey"], "build")
        self.assertEqual(validation["failAction"], "selected_step")
        self.assertGreaterEqual(validation["maxRetries"], 10)

    def test_external_validation_fails_when_project_has_no_validation_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)

            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-1", "workspace": str(workspace), "project_path": str(project)}

            with self.assertRaises(WorkflowError):
                asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: FAIL", result)
            self.assertIn("No validation script found", result)

    def test_external_validation_runs_project_default_validation_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            (project / "validation.py").write_text(
                "from pathlib import Path\n"
                "Path('validated.txt').write_text('ok', encoding='utf-8')\n"
                "print('validation ok')\n",
                encoding="utf-8",
            )

            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {"id": "run-2", "workspace": str(workspace), "project_path": str(project)}
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("Script: validation.py", result)
            self.assertIn("validation ok", result)
            self.assertEqual((project / "validated.txt").read_text(encoding="utf-8"), "ok")

    def test_external_validation_uses_run_specific_relative_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            project.mkdir()
            output.mkdir(parents=True)
            (project / "tools").mkdir()
            (project / "tools" / "check_config.py").write_text(
                "from pathlib import Path\n"
                "Path('custom-validation.txt').write_text('ok', encoding='utf-8')\n"
                "print('custom validation ok')\n",
                encoding="utf-8",
            )

            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {
                "id": "run-3",
                "workspace": str(workspace),
                "project_path": str(project),
                "validation_script": "tools/check_config.py",
            }
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("Script: tools\\check_config.py", result.replace("/", "\\"))
            self.assertEqual((project / "custom-validation.txt").read_text(encoding="utf-8"), "ok")

    def test_external_validation_uses_run_specific_absolute_script_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            output = workspace / "output"
            external = Path(tmp) / "provided_validator.py"
            project.mkdir()
            output.mkdir(parents=True)
            external.write_text("print('absolute validation ok')\n", encoding="utf-8")

            service = WorkflowFunctionService(log=_noop_log, refresh_artifacts=_noop_refresh)
            run = {
                "id": "run-4",
                "workspace": str(workspace),
                "project_path": str(project),
                "validation_script": str(external),
            }
            asyncio.run(service.call_python_function(run, "run_external_validation", output, "external-validation-result.md"))

            result = (output / "external-validation-result.md").read_text(encoding="utf-8")
            self.assertIn("Status: PASS", result)
            self.assertIn("absolute validation ok", result)


if __name__ == "__main__":
    unittest.main()
