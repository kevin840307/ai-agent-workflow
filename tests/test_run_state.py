from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.run_state import RunState


class FakeStore:
    def __init__(self, data: dict) -> None:
        self.data = data

    async def read(self) -> dict:
        return self.data

    async def mutate(self, fn):
        return fn(self.data)


class FakeBus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append((run_id, event))


class RunStateTests(unittest.TestCase):
    def test_refresh_artifacts_collects_workflow_files_and_expected_outputs(self) -> None:
        asyncio.run(self._run_refresh_case())

    def test_record_step_event_updates_run_and_step_timeline(self) -> None:
        asyncio.run(self._run_record_step_event_case())

    def test_append_failure_feedback_includes_recovery_analysis_and_stop_condition(self) -> None:
        asyncio.run(self._run_append_failure_feedback_case())

    async def _run_refresh_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir()
            (workspace / "prompts").mkdir()
            (workspace / ".workflow").mkdir()
            (workspace / "requirement.md").write_text("requirement", encoding="utf-8")
            (workspace / "output" / "spec.md").write_text("spec", encoding="utf-8")
            (workspace / "input" / "failure-feedback.md").write_text("feedback", encoding="utf-8")
            (workspace / "prompts" / "generate_spec.md").write_text("prompt", encoding="utf-8")
            (workspace / ".workflow" / "run-log.md").write_text("log", encoding="utf-8")
            (workspace / ".workflow" / "state.json").write_text("{}", encoding="utf-8")

            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "steps": [
                    {
                        "key": "generate_spec",
                        "config": {
                            "outputFile": "spec.md",
                            "expectedFiles": ["spec.md"],
                        },
                    }
                ],
            }
            bus = FakeBus()
            state = RunState(FakeStore({"runs": [run]}), bus)
            await state.refresh_artifacts("run-1")

            paths = {artifact["path"] for artifact in run["artifacts"]}
            self.assertIn("requirement.md", paths)
            self.assertIn("output/spec.md", paths)
            self.assertIn("input/failure-feedback.md", paths)
            self.assertIn("prompts/generate_spec.md", paths)
            self.assertIn(".workflow/run-log.md", paths)
            self.assertTrue(bus.events)

    async def _run_record_step_event_case(self) -> None:
        run = {
            "id": "run-1",
            "workspace": ".",
            "steps": [{"key": "build", "retry_count": 2}],
        }
        bus = FakeBus()
        state = RunState(FakeStore({"runs": [run]}), bus)

        await state.reset_retry_counts_from("run-1", 0)
        await state.record_step_event(
            "run-1",
            "build",
            "manual_retry",
            "Manual retry requested from build; retry counters were reset from this step.",
        )

        self.assertEqual(run["steps"][0]["retry_count"], 0)
        self.assertEqual(run["timeline"][0]["kind"], "manual_retry")
        self.assertEqual(run["steps"][0]["events"][0]["kind"], "manual_retry")
        self.assertTrue(bus.events)

    async def _run_append_failure_feedback_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            (workspace / "input").mkdir(parents=True)
            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "steps": [{"key": "build", "retry_count": 1, "events": []}],
                "timeline": [],
            }
            bus = FakeBus()
            state = RunState(FakeStore({"runs": [run]}), bus)

            await state.append_failure_feedback(
                run,
                "run_external_validation",
                "build",
                RuntimeError("validation failed"),
                1,
                12,
            )

            feedback = (workspace / "input" / "failure-feedback.md").read_text(encoding="utf-8")
            self.assertIn("### Recovery analysis", feedback)
            self.assertIn("Stop condition", feedback)
            self.assertIn("validation script is the acceptance gate", feedback)
            self.assertEqual(run["steps"][0]["events"][0]["kind"], "retry")



if __name__ == "__main__":
    unittest.main()
