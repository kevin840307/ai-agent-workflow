from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.persistence.sqlite_store import SQLiteStore
from app.runtime_modules.events import EventBus
from app.runtime_modules.run_state import RunState
from app.services.workflow_asset_validator import validate_all_workflows
from app.workflow_runtime.run_artifacts import ARTIFACT_SCHEMA, read_run_artifact_index


class FullSystemOptimizationRound4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_store_event_step_artifact_status_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            run_dir = project / ".qwen-workflow" / "runs" / "session-s" / "run-r"
            (run_dir / ".workflow").mkdir(parents=True)
            (run_dir / "output").mkdir(parents=True)
            (run_dir / "output" / "build-result.md").write_text("Status: PASS\n", encoding="utf-8")
            store = SQLiteStore(Path(tmp) / "state.sqlite3", default_project_path=lambda: str(project), default_steps=lambda: [])
            store.save_sync(
                {
                    "sessions": [],
                    "messages": [],
                    "workflow_configs": [],
                    "runs": [
                        {
                            "id": "r",
                            "session_id": "s",
                            "status": "queued",
                            "workspace": str(run_dir),
                            "project_path": str(project),
                            "steps": [{"key": "build", "status": "pending", "retry_count": 0}],
                            "artifacts": [],
                            "timeline": [],
                        }
                    ],
                }
            )
            state = RunState(store, EventBus())
            await state.transition_run_status("r", "running", extra={"started_at": "now"})
            await state.set_step("r", "build", "running")
            retry_count = await state.increment_step_retry("r", "build")
            await state.record_step_event("r", "build", "custom.event", "custom event message")
            await state.set_step("r", "build", "passed")
            await state.refresh_artifacts("r")
            run = await state.get_run_record("r")
            self.assertEqual(run["status"], "running")
            self.assertEqual(run["steps"][0]["status"], "passed")
            self.assertEqual(retry_count, 1)
            self.assertTrue(run.get("events"), "Run-level EventStore copy should be populated")
            self.assertTrue(any(item["path"] == "output/build-result.md" for item in run["artifacts"]))

    async def test_workflow_asset_validator_v3_emits_normalized_step_contracts(self) -> None:
        result = await validate_all_workflows()
        self.assertEqual(result["schema"], "aiwf.workflow-validator.v3")
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["workflow_count"], 1)
        for workflow in result["workflows"]:
            self.assertEqual(workflow["schema"], "aiwf.workflow-contract.v1")
            self.assertTrue(workflow["step_contracts"])
            for contract in workflow["step_contracts"]:
                self.assertIn("key", contract)
                self.assertIn("ai_decision_allowed", contract)
                self.assertIn("deterministic_validation", contract)

    async def test_standard_artifacts_v2_emit_final_report_and_debug_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            (run_dir / ".workflow").mkdir(parents=True)
            run = {
                "id": "r",
                "session_id": "s",
                "workflow_id": "general-auto-development",
                "status": "done",
                "workspace": str(run_dir),
                "project_path": str(run_dir),
                "steps": [{"key": "build", "status": "passed", "retry_count": 0}],
            }
            (run_dir / ".workflow" / "state.json").write_text(json.dumps(run), encoding="utf-8")
            index = read_run_artifact_index(run)
            self.assertEqual(index["schema"], ARTIFACT_SCHEMA)
            paths = {item["path"] for item in index["records"]}
            self.assertIn("reports/final-report.md", paths)
            self.assertIn("metadata/debug-bundle.json", paths)
            self.assertTrue((run_dir / ".workflow" / "artifacts" / "reports" / "final-report.md").exists())


class StaticArchitectureRound4Tests(unittest.TestCase):
    def test_actions_runtime_is_split_into_focused_mixins(self) -> None:
        root = Path(__file__).resolve().parents[1]
        actions = root / "app" / "workflow_runtime" / "actions.py"
        self.assertLess(len(actions.read_text(encoding="utf-8").splitlines()), 120)
        for rel in [
            "app/workflow_runtime/base_actions.py",
            "app/workflow_runtime/general_actions.py",
            "app/workflow_runtime/adaptive_actions.py",
            "app/workflow_runtime/consensus_actions.py",
            "app/workflow_runtime/action_dispatcher.py",
            "app/workflow_engine/kernel.py",
            "app/workflow_engine/runner.py",
            "app/workflow_engine/contracts.py",
        ]:
            self.assertTrue((root / rel).exists(), rel)

    def test_agent_subprocess_paths_use_shared_supervisor(self) -> None:
        root = Path(__file__).resolve().parents[1]
        qwen = (root / "app/runtime_modules/qwen.py").read_text(encoding="utf-8")
        providers = "\n".join(path.read_text(encoding="utf-8") for path in (root / "app/workflow/agents/providers").glob("*.py"))
        self.assertIn("run_agent_command_sync", qwen)
        self.assertIn("run_supervised_process", qwen)
        self.assertNotIn("subprocess.run(", qwen)
        self.assertIn("run_process_stream", providers)

    def test_workflow_console_and_local_first_docs_exist(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index = (root / "static/index.html").read_text(encoding="utf-8")
        self.assertIn("Run Center", index)
        self.assertIn("看懂目前進度與驗證結果", index)
        self.assertTrue((root / "doc/en/ARCHITECTURE.md").exists())
        self.assertTrue((root / "doc/zh-TW/ARCHITECTURE.md").exists())
        schema_doc = (root / "data/ai-workflow/WORKFLOW_CONTRACT_SCHEMA.md").read_text(encoding="utf-8")
        self.assertIn("aiwf.workflow-validator.v3", schema_doc)

    def test_runtime_api_exposes_workflow_engine_kernel(self) -> None:
        from app.runtime_modules import api as runtime

        self.assertEqual(runtime.workflow_kernel.describe()["schema"], "aiwf.workflow-engine-kernel.v1")
        self.assertIn("WorkflowExecutor", runtime.workflow_kernel.describe()["executor"])


if __name__ == "__main__":
    unittest.main()
