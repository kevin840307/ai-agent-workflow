from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.services import artifact_service, workflow_service
from app.core.paths import atomic_write_text
from app.workflow_runtime.builtin_functions.security_candidates import _security_heuristic_candidates_from_context
from app.workflow_runtime.step_config import initial_steps
from app.security.agent_project_config import ensure_agent_project_configs
from app.runtime_modules.files import apply_extracted_files
from app.runtime_modules.errors import WorkflowError
import json


class RuntimeSafetyTests(unittest.TestCase):
    def test_initial_steps_preserve_retry_and_consensus_config(self) -> None:
        steps = initial_steps(
            [
                {
                    "key": "consensus_security_scan",
                    "name": "Consensus Security Scan",
                    "type": "python",
                    "function": "consensus_agent",
                    "maxRetries": 7,
                    "retryFromStepKey": "collect_security_manifest",
                    "freshSessionPerAgent": True,
                }
            ]
        )

        self.assertEqual(steps[0]["max_retries"], 7)
        self.assertEqual(steps[0]["retry_from_step_key"], "collect_security_manifest")
        self.assertTrue(steps[0]["config"]["freshSessionPerAgent"])
        self.assertEqual(steps[0]["config"]["function"], "consensus_agent")

    def test_artifact_api_rejects_paths_outside_workspace(self) -> None:
        async def run_case() -> None:
            original_get_run = workflow_service.get_run
            with tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp) / "workspace"
                workspace.mkdir()

                async def fake_get_run(run_id: str) -> dict:
                    return {"id": run_id, "workspace": str(workspace)}

                workflow_service.get_run = fake_get_run
                try:
                    with self.assertRaises(HTTPException) as raised:
                        await artifact_service.get_artifact("run-1:..|outside.md")
                    self.assertEqual(raised.exception.status_code, 404)
                finally:
                    workflow_service.get_run = original_get_run

        asyncio.run(run_case())

    def test_security_heuristics_use_actual_context_paths(self) -> None:
        context = """
Status: DONE

# Security Scan Scope

## Security-Relevant Excerpts

### app/config.py
```text
12: API_TOKEN = "Bearer abc.def.ghi"
13: PASSWORD = "plain-text"
```
"""

        candidates = _security_heuristic_candidates_from_context(context)

        self.assertTrue(candidates)
        evidence_blob = "\n".join(candidate["Evidence"] for candidate in candidates)
        file_blob = "\n".join(candidate["File"] for candidate in candidates)
        self.assertIn("app/config.py", evidence_blob + file_blob)
        self.assertNotIn("SGOAuto", evidence_blob + file_blob)

    def test_atomic_write_text_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.md"
            atomic_write_text(path, "first")
            atomic_write_text(path, "second")

            self.assertEqual(path.read_text(encoding="utf-8"), "second")
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_atomic_write_text_retries_transient_replace_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            calls = {"count": 0}
            real_replace = os.replace

            def flaky_replace(src, dst):
                calls["count"] += 1
                if calls["count"] < 3:
                    raise PermissionError(5, "Access is denied")
                return real_replace(src, dst)

            with patch("app.core.paths.os.replace", side_effect=flaky_replace), patch(
                "app.core.paths.time.sleep", return_value=None
            ):
                atomic_write_text(path, '{"ok": true}')

            self.assertEqual(path.read_text(encoding="utf-8"), '{"ok": true}')
            self.assertEqual(calls["count"], 3)
            self.assertFalse(list(Path(tmp).glob("*.tmp")))

    def test_project_agent_configs_restrict_writes_but_allow_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()

            written = ensure_agent_project_configs(project)

            self.assertTrue((project / ".qwen" / "settings.json").is_file())
            self.assertTrue((project / ".qwen" / "QWEN.md").is_file())
            self.assertTrue((project / "opencode.json").is_file())
            self.assertTrue(written)

            qwen = json.loads((project / ".qwen" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(qwen["tools"]["approvalMode"], "auto-edit")
            self.assertEqual(qwen["aiWorkflowGuard"]["writePolicy"], "project_only")
            self.assertEqual(qwen["aiWorkflowGuard"]["readPolicy"], "unrestricted")

            opencode = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
            self.assertEqual(opencode["permission"]["external_directory"]["*"], "allow")
            self.assertEqual(opencode["permission"]["edit"][".qwen/**"], "deny")
            self.assertEqual(opencode["permission"]["edit"]["opencode.json"], "deny")
            self.assertEqual(opencode["permission"]["bash"]["*"], "deny")

    def test_agent_file_blocks_cannot_edit_managed_agent_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            with self.assertRaisesRegex(WorkflowError, "managed agent guard config"):
                apply_extracted_files(project, [("opencode.json", "{}\n")])
            with self.assertRaisesRegex(WorkflowError, "reserved directory"):
                apply_extracted_files(project, [(".qwen/settings.json", "{}\n")])


if __name__ == "__main__":
    unittest.main()
