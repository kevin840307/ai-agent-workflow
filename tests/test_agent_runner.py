from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.workflow_runtime.agent_step_runner import AgentStepRunner
from app.workflow_runtime.agents import AgentResult
from app.workflow_runtime.prompt_builder import PromptBuildResult
from app.runtime_modules.errors import WorkflowError


class FakeBus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, run_id: str, event: dict) -> None:
        self.events.append((run_id, event))


class FakeAgent:
    name = "qwen"

    def __init__(self) -> None:
        self.requests = []

    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(output="Status: PASS\n\nok", session_id=request.session_id)

    def command_preview(self, request) -> str:
        return "fake qwen"

    def health(self) -> dict:
        return {"name": self.name}


class RecoveringFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise WorkflowError("session not found")
        return AgentResult(output="Status: PASS\n\nrecovered", session_id=request.session_id)


class FakeAgentManager:
    def __init__(self, agent: FakeAgent) -> None:
        self.agent = agent

    def resolve(self, step_config=None, *, agent_name=None) -> FakeAgent:
        return self.agent


class FakePromptBuilder:
    def build(self, run, step_key, prompt_name, *, allow_interaction, agent_name="qwen") -> PromptBuildResult:
        return PromptBuildResult(
            prompt="test prompt",
            prompt_template="test prompt",
            skill_files=[],
            skill_context="",
            relative_prompt_path=f"prompts/{step_key}.md",
        )


class AgentRunnerTests(unittest.TestCase):
    def test_qwen_uses_project_session_by_default(self) -> None:
        asyncio.run(self._run_session_case(fresh_session=False, fresh_per_agent=True, expected_session="qwen-session-1"))

    def test_fresh_qwen_consensus_session_omits_project_session_id(self) -> None:
        asyncio.run(self._run_session_case(fresh_session=True, fresh_per_agent=True, expected_session=None))

    def test_fresh_session_without_force_flag_keeps_project_session_id(self) -> None:
        asyncio.run(self._run_session_case(fresh_session=True, fresh_per_agent=False, expected_session="qwen-session-1"))

    def test_recoverable_session_error_retries_once_without_session_id(self) -> None:
        asyncio.run(self._run_session_recovery_case())

    async def _run_session_recovery_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            agent = RecoveringFakeAgent()
            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(agent),
                prompt_builder=FakePromptBuilder(),
                bus=FakeBus(),
                log=lambda run, message: _noop(),
                refresh_artifacts=lambda run_id: _noop(),
                append_session_message=lambda session_id, role, content: _noop_dict(),
            )
            run = {
                "id": "run-1",
                "session_id": "session-1",
                "qwen_session_id": "qwen-session-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "steps": [{"key": "build", "agent": "qwen", "allow_interaction": False, "config": {}}],
            }

            await runner.run(run, "build", "05_build.md", "build-result.md")

            self.assertEqual(len(agent.requests), 2)
            self.assertEqual(agent.requests[0].session_id, "qwen-session-1")
            self.assertIsNone(agent.requests[1].session_id)

    async def _run_session_case(self, *, fresh_session: bool, fresh_per_agent: bool, expected_session: str | None) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            agent = FakeAgent()
            bus = FakeBus()
            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(agent),
                prompt_builder=FakePromptBuilder(),
                bus=bus,
                log=lambda run, message: _noop(),
                refresh_artifacts=lambda run_id: _noop(),
                append_session_message=lambda session_id, role, content: _noop_dict(),
            )
            run = {
                "id": "run-1",
                "session_id": "session-1",
                "qwen_session_id": "qwen-session-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "steps": [
                    {
                        "key": "consensus_security_scan",
                        "agent": "qwen",
                        "allow_interaction": False,
                        "config": {"freshSessionPerAgent": fresh_per_agent},
                    }
                ],
            }

            await runner.run(
                run,
                "consensus_security_scan",
                "00_security_candidate_scan.md",
                "security-candidates-agent-1.md",
                fresh_session=fresh_session,
            )

            self.assertEqual(agent.requests[-1].session_id, expected_session)


async def _noop():
    return None


async def _noop_dict():
    return {}


if __name__ == "__main__":
    unittest.main()
