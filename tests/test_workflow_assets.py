from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import workflow_asset_service
from app.workflow_runtime import prompt_builder
from app.workflow_runtime.functions import WorkflowFunctionService


class WorkflowAssetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.global_root = self.root / "global-ai-workflow"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.original_global = workflow_asset_service.GLOBAL_ASSET_ROOT
        self.original_prompt_global = prompt_builder.GLOBAL_ASSET_ROOT
        workflow_asset_service.GLOBAL_ASSET_ROOT = self.global_root
        prompt_builder.GLOBAL_ASSET_ROOT = self.global_root
        workflow_asset_service.ensure_asset_dirs(str(self.project_root))

    def tearDown(self) -> None:
        workflow_asset_service.GLOBAL_ASSET_ROOT = self.original_global
        prompt_builder.GLOBAL_ASSET_ROOT = self.original_prompt_global
        self.tmp.cleanup()

    def test_asset_api_writes_and_lists_separated_skill_contract_and_python_files(self) -> None:
        with TestClient(app) as client:
            skill = client.put(
                "/api/workflow-assets/file",
                json={"path": "steps/spec.md", "content": "Skill prompt", "scope": "global"},
            )
            contract = client.put(
                "/api/workflow-assets/file",
                json={
                    "path": "contracts/spec.yaml",
                    "content": "id: spec\nskill: steps/spec.md\nretry: 4\noutputs:\n  - spec.md\nagent: opencode\n",
                    "scope": "global",
                },
            )
            validator = client.put(
                "/api/workflow-assets/file",
                json={"path": "validators/check.py", "content": "print('ok')\n", "scope": "project", "project_path": str(self.project_root)},
            )
            self.assertEqual(skill.status_code, 200)
            self.assertEqual(contract.status_code, 200)
            self.assertEqual(validator.status_code, 200)

            listed = client.get("/api/workflow-assets", params={"project_path": str(self.project_root)})
            self.assertEqual(listed.status_code, 200)
            paths = {item["path"] for item in listed.json()["assets"]}
            self.assertIn("steps/spec.md", paths)
            self.assertIn("contracts/spec.yaml", paths)
            self.assertIn("validators/check.py", paths)

    def test_apply_contract_to_workflow_keeps_skill_and_metadata_separate(self) -> None:
        workflow_asset_service.write_asset("steps/build.md", "Build prompt", scope="global")
        workflow_asset_service.write_asset(
            "contracts/build.yaml",
            "id: build-contract\nskill: steps/build.md\nretry: 7\noutputs:\n  - build-result.md\nvalidator: validators/check.py\nagent: qwen\ntimeout: 120\n",
            scope="global",
        )
        workflow = {"steps": [{"key": "build", "name": "Build", "contractId": "build"}]}

        applied = workflow_asset_service.apply_contracts_to_workflow(workflow, str(self.project_root))
        step = applied["steps"][0]

        self.assertEqual(step["contractId"], "build-contract")
        self.assertEqual(step["templatePath"], "steps/build.md")
        self.assertEqual(step["skillPath"], "steps/build.md")
        self.assertEqual(step["maxRetries"], 7)
        self.assertEqual(step["expectedFiles"], ["build-result.md"])
        self.assertEqual(step["validator"], "validators/check.py")
        self.assertEqual(step["agent"], "qwen")
        self.assertTrue(step["timeoutEnabled"])

    def test_prompt_builder_reads_project_local_ai_workflow_step_before_global(self) -> None:
        workflow_asset_service.write_asset("steps/shared.md", "Global {{requirement}}", scope="global")
        workflow_asset_service.write_asset(
            "steps/shared.md",
            "Project {{requirement}}",
            project_path=str(self.project_root),
            scope="project",
        )
        run_dir = self.root / "run"
        (run_dir / "output").mkdir(parents=True)
        (run_dir / "input").mkdir(parents=True)
        (run_dir / "requirement.md").write_text("hello", encoding="utf-8")
        run = {
            "id": "run-1",
            "workspace": str(run_dir),
            "project_path": str(self.project_root),
            "steps": [{"key": "demo", "config": {"templatePath": "steps/shared.md"}}],
        }

        result = prompt_builder.PromptBuilder().build(run, "demo", "steps/shared.md", allow_interaction=False)

        self.assertIn("Project hello", result.prompt)
        self.assertNotIn("Global hello", result.prompt)

    def test_python_asset_run_function_can_be_called_by_api_runtime(self) -> None:
        workflow_asset_service.write_asset(
            "validators/api_check.py",
            "def run(context, artifact=None):\n"
            "    context.write_text(context.output_dir / 'api-validator-ok.md', f'api {artifact}')\n"
            "    return 'Status: PASS from api mode'\n",
            project_path=str(self.project_root),
            scope="project",
        )
        run_dir = self.root / "run-python-api"
        output_dir = run_dir / "output"
        output_dir.mkdir(parents=True)
        run = {"id": "run-api", "workspace": str(run_dir), "project_path": str(self.project_root)}
        service = WorkflowFunctionService(log=lambda *_: None, refresh_artifacts=lambda *_: None)

        import asyncio

        asyncio.run(service.call_python_function(run, "validators/api_check.py", output_dir, "artifact.md"))

        self.assertEqual((output_dir / "api-validator-ok.md").read_text(encoding="utf-8"), "api artifact.md")
        self.assertIn("api mode", (output_dir / "api_check-result.md").read_text(encoding="utf-8"))

    def test_python_asset_without_run_falls_back_to_cli_contract(self) -> None:
        workflow_asset_service.write_asset(
            "validators/check.py",
            "from pathlib import Path\n"
            "import argparse\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--workspace')\n"
            "parser.add_argument('--project')\n"
            "parser.add_argument('--output')\n"
            "parser.add_argument('--artifact')\n"
            "args = parser.parse_args()\n"
            "Path(args.output, 'validator-ok.md').write_text('ok', encoding='utf-8')\n",
            project_path=str(self.project_root),
            scope="project",
        )
        run_dir = self.root / "run-python"
        output_dir = run_dir / "output"
        output_dir.mkdir(parents=True)
        run = {"id": "run-2", "workspace": str(run_dir), "project_path": str(self.project_root)}
        service = WorkflowFunctionService(log=lambda *_: None, refresh_artifacts=lambda *_: None)

        import asyncio

        asyncio.run(service.call_python_function(run, "validators/check.py", output_dir))

        self.assertEqual((output_dir / "validator-ok.md").read_text(encoding="utf-8"), "ok")

    def test_rejects_invalid_python_asset(self) -> None:
        with self.assertRaises(SyntaxError):
            workflow_asset_service.write_asset("validators/broken.py", "def broken(:\n", scope="global")


if __name__ == "__main__":
    unittest.main()
