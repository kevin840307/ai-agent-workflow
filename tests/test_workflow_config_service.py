from __future__ import annotations

import asyncio
import shutil
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import workflow_asset_service, workflow_config_service


class WorkflowConfigServiceTests(unittest.TestCase):
    def test_internal_asset_writer_persists_prompt_content(self) -> None:
        workflow_id = "test-prompt-persistence"
        workflow_file = workflow_config_service.workflow_file(workflow_id)
        step_dir = workflow_config_service.STEPS_DIR / workflow_id
        contract_dir = workflow_config_service.CONTRACTS_DIR / workflow_id
        for target in (workflow_file, step_dir, contract_dir):
            if target.is_file(): target.unlink()
            elif target.exists(): shutil.rmtree(target)
        workflow = {
            "id": workflow_id, "name": "Test Prompt Persistence", "kind": "custom", "folderName": workflow_id,
            "steps": [{"id": "step-1", "key": "generate_doc", "name": "Generate Doc", "type": "ai", "templatePath": "prompts/generate_doc.md", "templateContent": "Hello {{requirement}}", "filename": "doc.md", "outputFile": "doc.md"}],
        }
        try:
            saved = workflow_config_service.write_workflow_assets(workflow)
            prompt_path = workflow_config_service.STEPS_DIR / workflow_id / "generate_doc.md"
            self.assertTrue(prompt_path.exists())
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "Hello {{requirement}}")
            loaded = workflow_asset_service.load_workflow_asset(workflow_id)
            loaded = workflow_config_service.read_prompt_files(loaded, workflow_id)
            self.assertEqual(loaded["steps"][0]["templateContent"], "Hello {{requirement}}")
            self.assertEqual(saved["id"], workflow_id)
        finally:
            for target in (workflow_file, step_dir, contract_dir):
                if target.is_file(): target.unlink()
                elif target.exists(): shutil.rmtree(target)

    def test_product_catalog_contains_only_three_read_only_workflows(self) -> None:
        listed = asyncio.run(workflow_config_service.list_workflows())
        ids = [listed["system"]["id"], *[item["id"] for item in listed["systems"]], *[item["id"] for item in listed["custom"]]]
        self.assertEqual(ids, ["general-auto-development", "adaptive-auto-workflow", "security-scan"])
        self.assertEqual(listed["custom"], [])
        for workflow_id in ids:
            loaded = asyncio.run(workflow_config_service.get_workflow(workflow_id))
            self.assertTrue(loaded["protected"])
            self.assertFalse(loaded["deletable"])
        with self.assertRaises(HTTPException) as create_error:
            asyncio.run(workflow_config_service.upsert_workflow({"id": "custom"}))
        self.assertEqual(create_error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as delete_error:
            asyncio.run(workflow_config_service.delete_workflow("general-auto-development"))
        self.assertEqual(delete_error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as missing_error:
            asyncio.run(workflow_config_service.get_workflow("unsupported"))
        self.assertEqual(missing_error.exception.status_code, 404)

    def test_workflow_lint_rejects_bad_targets_paths_and_functions(self) -> None:
        workflow = {
            "id": "test-invalid-workflow", "name": "Invalid Workflow", "kind": "custom", "folderName": "test-invalid-workflow",
            "steps": [{"id": "step-1", "key": "build", "name": "Build", "type": "ai", "templatePath": "../outside.md", "filename": "build-result.md", "outputFile": "build-result.md", "expectedFiles": ["../outside.md"], "retryFromStepKey": "missing_step", "function": "missing_function"}],
        }
        payload = asyncio.run(workflow_config_service.lint_workflow_config(workflow))
        self.assertFalse(payload["ok"])
        messages = " ".join(issue["message"] for issue in payload["issues"])
        self.assertIn("Unknown Python function", messages)
        self.assertIn("Step target does not exist", messages)
        self.assertIn("Unsafe expected file path", messages)

    def test_workflow_lint_api_returns_issues_without_saving(self) -> None:
        with TestClient(app) as client:
            response = client.post("/api/workflows/lint", json={"id": "lint-api-test", "name": "Lint API", "steps": [{"id": "step-1", "key": "validate", "type": "python", "function": "missing_function"}]})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["issues"])


if __name__ == "__main__":
    unittest.main()
