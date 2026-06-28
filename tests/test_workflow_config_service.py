from __future__ import annotations

import asyncio
import shutil
import unittest

from fastapi import HTTPException

from app.services import workflow_config_service


class WorkflowConfigServiceTests(unittest.TestCase):
    def test_upsert_workflow_persists_prompt_content_to_bundle(self) -> None:
        asyncio.run(self._run_prompt_persistence_case())

    async def _run_prompt_persistence_case(self) -> None:
        workflow_id = "test-prompt-persistence"
        folder = workflow_config_service.WORKFLOWS_DIR / workflow_id
        if folder.exists():
            shutil.rmtree(folder)

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
            prompt_path = folder / "prompts" / "generate_doc.md"

            self.assertTrue(prompt_path.exists())
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "Hello {{requirement}}")
            self.assertEqual(saved["steps"][0]["templateContent"], "Hello {{requirement}}")

            loaded = await workflow_config_service.get_workflow(workflow_id)
            self.assertEqual(loaded["steps"][0]["templateContent"], "Hello {{requirement}}")
            self.assertEqual(loaded["steps"][0]["templatePath"], "prompts/generate_doc.md")
        finally:
            if folder.exists():
                shutil.rmtree(folder)

    def test_system_workflow_is_protected_and_custom_delete_removes_folder(self) -> None:
        asyncio.run(self._run_delete_protection_case())

    async def _run_delete_protection_case(self) -> None:
        workflow_id = "test-delete-workflow"
        folder = workflow_config_service.WORKFLOWS_DIR / workflow_id
        if folder.exists():
            shutil.rmtree(folder)

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
        self.assertTrue(folder.exists())
        result = await workflow_config_service.delete_workflow(workflow_id)
        self.assertEqual(result, {"ok": True})
        self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
