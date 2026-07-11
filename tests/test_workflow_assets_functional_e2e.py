from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import workflow_asset_service, workflow_config_service
from app.workflow_runtime import prompt_builder


class WorkflowAssetsFunctionalE2ETests(unittest.TestCase):
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
        workflow_config_service._sync_asset_paths()
        workflow_asset_service.ensure_asset_dirs(str(self.project_root))

    def tearDown(self) -> None:
        workflow_asset_service.GLOBAL_ASSET_ROOT = self.original_global
        prompt_builder.GLOBAL_ASSET_ROOT = self.original_prompt_global
        workflow_config_service._sync_asset_paths()
        self.tmp.cleanup()

    def test_http_asset_crud_to_runtime_workflow_resolution(self) -> None:
        with TestClient(app) as client:
            writes = [
                {"path": "steps/e2e/spec.md", "content": "Write spec for {{requirement}}", "scope": "global"},
                {"path": "functions/e2e/check.py", "content": "def run(context, artifact=None):\n    return 'Status: PASS\\n'\n", "scope": "global"},
                {"path": "contracts/e2e/spec.yaml", "content": "id: e2e-spec\nname: E2E Spec\ntype: python\nskill: steps/e2e/spec.md\nfunction: functions/e2e/check.py\noutputs:\n  - spec.md\nretry: 1\nallowInteraction: false\n", "scope": "global"},
                {"path": "workflows/e2e.workflow", "content": "id: e2e\nname: E2E Workflow\nsteps:\n  - contract: contracts/e2e/spec.yaml\n", "scope": "global"},
            ]
            for body in writes:
                response = client.put("/api/workflow-assets/file", json=body)
                self.assertEqual(response.status_code, 200, response.text)

            listed = client.get("/api/workflow-assets")
            self.assertEqual(listed.status_code, 200)
            self.assertIn("workflows/e2e.workflow", {item["path"] for item in listed.json()["assets"]})

            workflow = workflow_asset_service.load_workflow_asset("e2e")
            workflow = workflow_config_service.read_prompt_files(workflow, workflow.get("folderName") or workflow.get("id"))

        self.assertEqual(workflow["id"], "e2e")
        self.assertEqual(workflow["steps"][0]["skillPath"], "steps/e2e/spec.md")
        self.assertEqual(workflow["steps"][0]["function"], "functions/e2e/check.py")
        self.assertFalse(workflow["steps"][0]["allowInteraction"])

    def test_project_asset_overrides_global_asset_through_same_ui_cli_resolver(self) -> None:
        workflow_asset_service.write_asset("steps/shared.md", "global prompt", scope="global")
        workflow_asset_service.write_asset("steps/shared.md", "project prompt", project_path=str(self.project_root), scope="project")
        workflow_asset_service.write_asset("contracts/shared.yaml", "id: shared\nskill: steps/shared.md\n", scope="global")
        workflow_asset_service.write_asset("workflows/shared.workflow", "contract: shared\n", scope="global")

        workflow = workflow_asset_service.load_workflow_asset("shared", project_path=str(self.project_root))
        workflow = workflow_config_service.read_prompt_files(workflow, workflow.get("folderName") or workflow.get("id"))

        self.assertEqual(workflow["steps"][0]["templateContent"], "project prompt")


if __name__ == "__main__":
    unittest.main()
