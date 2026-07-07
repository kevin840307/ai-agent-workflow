from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agents.process_supervisor import ProcessSupervisorOptions, normalize_cwd, run_supervised_process
from app.runtime_modules.errors import WorkflowError
from app.services.workflow_service import default_patch_mode_for_agent
from app.workflow.agents.base import AgentRequest
from app.workflow.agents.providers.generic_cli import GenericCliAdapter


class ProcessSupervisorAndPatchDefaultTests(unittest.TestCase):
    def test_supervisor_runs_in_requested_cwd_and_cleans_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = {}
            result = asyncio.run(
                run_supervised_process(
                    ProcessSupervisorOptions(
                        command=[sys.executable, "-c", "import os; print(os.getcwd())"],
                        cwd=Path(tmp),
                        run_id="run-1",
                        process_registry=registry,
                        timeout_sec=10,
                    )
                )
            )
            self.assertEqual(Path(result.stdout).resolve(), Path(tmp).resolve())
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("run-1", registry)

    def test_supervisor_rejects_missing_cwd_before_spawning_agent(self) -> None:
        with self.assertRaises(WorkflowError):
            normalize_cwd(Path("/path/that/does/not/exist/for/aiwf"))

    def test_supervisor_timeout_raises_workflow_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkflowError, "timed out"):
                asyncio.run(
                    run_supervised_process(
                        ProcessSupervisorOptions(
                            command=[sys.executable, "-c", "import time; time.sleep(3)"],
                            cwd=Path(tmp),
                            timeout_sec=0.1,
                        )
                    )
                )

    def test_generic_cli_stdin_mode_actually_sends_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = GenericCliAdapter(
                {
                    "name": "stdin-agent",
                    "bin": sys.executable,
                    "args": ["-c", "import sys; print(sys.stdin.read())"],
                    "promptMode": "stdin",
                    "timeoutSec": 10,
                }
            )
            request = AgentRequest(
                run_id="run-stdin",
                step_key="build",
                prompt="hello from stdin",
                cwd=Path(tmp),
                session_id=None,
            )
            result = asyncio.run(adapter.run_stream(request))
            self.assertIn("hello from stdin", result.output)

    def test_real_agents_default_to_patch_review_but_mocks_keep_auto_apply(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(default_patch_mode_for_agent("qwen"), "review")
            self.assertEqual(default_patch_mode_for_agent("opencode"), "review")
        with patch.dict(os.environ, {"QWEN_MOCK": "1", "OPENCODE_MOCK": "true"}, clear=True):
            self.assertEqual(default_patch_mode_for_agent("qwen"), "auto_apply")
            self.assertEqual(default_patch_mode_for_agent("opencode"), "auto_apply")
        with patch.dict(os.environ, {"AIWF_DEFAULT_PATCH_MODE": "dry-run"}, clear=True):
            self.assertEqual(default_patch_mode_for_agent("qwen"), "dry_run")

    def test_actions_dispatch_table_was_split_out_of_large_actions_file(self) -> None:
        root = Path(__file__).resolve().parents[1]
        actions_source = (root / "app/workflow_runtime/actions.py").read_text(encoding="utf-8")
        registry_source = (root / "app/workflow_runtime/actions_registry.py").read_text(encoding="utf-8")
        self.assertIn("builtin_action_for_step", actions_source)
        self.assertIn("def builtin_action_for_step", registry_source)
        self.assertLess(len(actions_source.splitlines()), 2450)


if __name__ == "__main__":
    unittest.main()
