from __future__ import annotations

import asyncio
import shutil
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import workflow_config_service


class WorkflowConfigServiceTests(unittest.TestCase):
    def test_upsert_workflow_persists_prompt_content_to_bundle(self) -> None:
        asyncio.run(self._run_prompt_persistence_case())

    async def _run_prompt_persistence_case(self) -> None:
        workflow_id = "test-prompt-persistence"
        workflow_file = workflow_config_service.workflow_file(workflow_id)
        step_dir = workflow_config_service.STEPS_DIR / workflow_id
        contract_dir = workflow_config_service.CONTRACTS_DIR / workflow_id
        for target in (workflow_file, step_dir, contract_dir):
            if target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)

        workflow = {
            "id": workflow_id,
            "name": "Test Prompt Persistence",
            "kind": "custom",
            "folderName": workflow_id,
            "steps": [
                {
                    "id": "step-1",
                    "key": "generate_doc",
                    "name": "Generate Doc",
                    "type": "ai",
                    "templatePath": "prompts/generate_doc.md",
                    "templateContent": "Hello {{requirement}}",
                    "filename": "doc.md",
                    "outputFile": "doc.md",
                }
            ],
        }

        try:
            saved = await workflow_config_service.upsert_workflow(workflow)
            prompt_path = workflow_config_service.STEPS_DIR / workflow_id / "generate_doc.md"
            contract_path = workflow_config_service.CONTRACTS_DIR / workflow_id / "generate_doc.yaml"

            self.assertTrue(prompt_path.exists())
            self.assertTrue(contract_path.exists())
            self.assertTrue(workflow_file.exists())
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "Hello {{requirement}}")
            self.assertEqual(saved["steps"][0]["templateContent"], "Hello {{requirement}}")

            loaded = await workflow_config_service.get_workflow(workflow_id)
            self.assertEqual(loaded["steps"][0]["templateContent"], "Hello {{requirement}}")
            self.assertEqual(loaded["steps"][0]["templatePath"], f"steps/{workflow_id}/generate_doc.md")
        finally:
            for target in (workflow_file, step_dir, contract_dir):
                if target.is_file():
                    target.unlink()
                elif target.exists():
                    shutil.rmtree(target)

    def test_system_workflow_is_protected_and_custom_delete_removes_folder(self) -> None:
        asyncio.run(self._run_delete_protection_case())

    def test_workflow_lint_rejects_bad_targets_paths_and_functions(self) -> None:
        asyncio.run(self._run_lint_rejection_case())

    def test_workflow_lint_api_returns_issues_without_saving(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/workflows/lint",
                json={
                    "id": "lint-api-test",
                    "name": "Lint API",
                    "steps": [
                        {
                            "id": "step-1",
                            "key": "validate",
                            "type": "python",
                            "validator": "missing_function",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["issues"])

    async def _run_lint_rejection_case(self) -> None:
        workflow = {
            "id": "test-invalid-workflow",
            "name": "Invalid Workflow",
            "kind": "custom",
            "folderName": "test-invalid-workflow",
            "steps": [
                {
                    "id": "step-1",
                    "key": "build",
                    "name": "Build",
                    "type": "ai",
                    "templatePath": "../outside.md",
                    "filename": "build-result.md",
                    "outputFile": "build-result.md",
                    "expectedFiles": ["../outside.md"],
                    "retryFromStepKey": "missing_step",
                    "validator": "missing_function",
                }
            ],
        }

        with self.assertRaises(HTTPException) as raised:
            await workflow_config_service.upsert_workflow(workflow)

        self.assertEqual(raised.exception.status_code, 400)
        detail = raised.exception.detail
        self.assertEqual(detail["code"], "WORKFLOW_CONFIG_INVALID")
        messages = " ".join(issue["message"] for issue in detail["details"]["issues"])
        self.assertIn("Unknown validator/function", messages)
        self.assertIn("Step target does not exist", messages)
        self.assertIn("Unsafe expected file path", messages)

    async def _run_delete_protection_case(self) -> None:
        workflow_id = "test-delete-workflow"
        workflow_file = workflow_config_service.workflow_file(workflow_id)
        step_dir = workflow_config_service.STEPS_DIR / workflow_id
        contract_dir = workflow_config_service.CONTRACTS_DIR / workflow_id
        for target in (workflow_file, step_dir, contract_dir):
            if target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)

        with self.assertRaises(HTTPException):
            await workflow_config_service.upsert_workflow({"id": workflow_config_service.SYSTEM_WORKFLOW_ID})
        with self.assertRaises(HTTPException):
            await workflow_config_service.delete_workflow(workflow_config_service.SYSTEM_WORKFLOW_ID)

        workflow = {
            "id": workflow_id,
            "name": "Delete Me",
            "kind": "custom",
            "folderName": workflow_id,
            "steps": [],
        }
        await workflow_config_service.upsert_workflow(workflow)
        self.assertTrue(workflow_file.exists())
        self.assertTrue(step_dir.exists())
        self.assertTrue(contract_dir.exists())
        result = await workflow_config_service.delete_workflow(workflow_id)
        self.assertEqual(result, {"ok": True})
        self.assertFalse(workflow_file.exists())
        self.assertFalse(step_dir.exists())
        self.assertFalse(contract_dir.exists())


if __name__ == "__main__":
    unittest.main()
