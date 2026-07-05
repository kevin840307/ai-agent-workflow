from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.workflow_runtime.agent_step_runner import AgentStepRunner
from app.workflow_runtime.agents import create_agent_manager, AgentRequest
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


class ToolCallFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(output='{"name": "use_exit_plan_mode"}', session_id=request.session_id)


class ToolCallFileFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output='```json\n{"name":"edit_file","arguments":{"file_path":"sorts.py","new_source":"def bubble_sort(items):\\n    return sorted(items)"}}\n```',
            session_id=request.session_id,
        )


class ToolCallFileVariantFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output='{"name":"write_file","parameters":"{\\"target_path\\":\\"tests/test_sorts.py\\",\\"content\\":\\"def test_sort():\\\\n    assert sorted([2, 1]) == [1, 2]\\"}"}',
            session_id=request.session_id,
        )


class ToolCallTripleQuotedFileFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output='```json\n{"name":"write_file","arguments":{"file_path":"sorts.py","new_source":"""def sort_values(items):\\n    return sorted(items)\\n"""}}\n```',
            session_id=request.session_id,
        )


class ToolCallPathPrefixedContentFakeAgent(FakeAgent):
    async def run_stream(self, request, on_output=None) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output='```json\n{"name":"auto_generation","arguments":{"new_source":"\n  sort.py: def insertion_sort(items):\\n      return sorted(items)\\n  "}}\n```',
            session_id=request.session_id,
        )


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

    def test_reuse_retry_uses_compact_prompt_after_failure_feedback(self) -> None:
        asyncio.run(self._run_compact_retry_case(compact_enabled=True, expected_compact=True))

    def test_reuse_retry_compaction_can_be_disabled_per_step(self) -> None:
        asyncio.run(self._run_compact_retry_case(compact_enabled=False, expected_compact=False))

    def test_tool_call_json_without_arguments_is_rejected_with_tool_name(self) -> None:
        asyncio.run(self._run_tool_call_json_case())

    def test_tool_call_json_with_file_content_is_rejected(self) -> None:
        asyncio.run(self._run_tool_call_file_block_case())

    def test_tool_call_json_with_string_parameters_is_rejected(self) -> None:
        asyncio.run(self._run_tool_call_string_parameters_case())

    def test_tool_call_json_with_triple_quoted_content_is_rejected(self) -> None:
        asyncio.run(self._run_tool_call_triple_quoted_content_case())

    def test_tool_call_json_with_path_prefixed_content_is_rejected(self) -> None:
        asyncio.run(self._run_tool_call_path_prefixed_content_case())

    def test_generic_cli_provider_can_be_added_from_settings(self) -> None:
        manager = create_agent_manager({
            "agents": {
                "default": "codex",
                "providers": {
                    "codex": {"type": "cli", "bin": "codex", "promptMode": "stdin", "mock": True},
                },
            }
        })

        agent = manager.resolve(agent_name="codex")
        preview = agent.command_preview(AgentRequest(run_id="run-1", step_key="demo", prompt="hello", cwd="/tmp", session_id="s1"))
        health = agent.health()

        self.assertIn("codex", manager.available_agent_names())
        self.assertEqual(manager.default_agent_name(), "codex")
        self.assertIn("codex", preview)
        self.assertEqual(health["type"], "cli")
        self.assertTrue(health["mock"])


    def test_step_metadata_overrides_provider_options_like_thinking(self) -> None:
        manager = create_agent_manager({
            "agents": {
                "default": "opencode",
                "providers": {
                    "opencode": {"type": "opencode_cli", "bin": "opencode", "mock": True, "thinking": False},
                },
            }
        })

        agent = manager.resolve({"agent": "opencode", "thinking": True, "model": "qwen3-coder", "timeoutSec": 99})
        health = agent.health()

        self.assertEqual(health["type"], "opencode_cli")
        self.assertTrue(health["thinking"])
        self.assertEqual(health["model"], "qwen3-coder")
        self.assertEqual(health["timeout_sec"], 99)

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

    async def _run_tool_call_json_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(ToolCallFakeAgent()),
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

            with self.assertRaisesRegex(WorkflowError, "use_exit_plan_mode"):
                await runner.run(run, "build", "05_build.md", "build-result.md")

    async def _run_tool_call_file_block_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(ToolCallFileFakeAgent()),
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

            with self.assertRaisesRegex(WorkflowError, "edit_file"):
                await runner.run(run, "build", "05_build.md", "build-result.md")

            self.assertFalse((project / "sorts.py").exists())

    async def _run_tool_call_string_parameters_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(ToolCallFileVariantFakeAgent()),
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
                "steps": [{"key": "generate_tests", "agent": "qwen", "allow_interaction": False, "config": {}}],
            }

            with self.assertRaisesRegex(WorkflowError, "write_file"):
                await runner.run(run, "generate_tests", "07_test.md", "test-plan.md")

            self.assertFalse((project / "tests" / "test_sorts.py").exists())

    async def _run_tool_call_triple_quoted_content_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(ToolCallTripleQuotedFileFakeAgent()),
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

            with self.assertRaisesRegex(WorkflowError, "write_file|edit_file"):
                await runner.run(run, "build", "05_build.md", "build-result.md")

            self.assertFalse((project / "sorts.py").exists())

    async def _run_tool_call_path_prefixed_content_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")

            runner = AgentStepRunner(
                agent_manager=FakeAgentManager(ToolCallPathPrefixedContentFakeAgent()),
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
                "steps": [{"key": "auto_generation", "agent": "qwen", "allow_interaction": False, "config": {}}],
            }

            with self.assertRaisesRegex(WorkflowError, "auto_generation|tool-call JSON"):
                await runner.run(run, "auto_generation", "00_auto_generation.md", "auto-generation-result.md")

            self.assertFalse((project / "sort.py").exists())

    async def _run_compact_retry_case(self, *, compact_enabled: bool, expected_compact: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            (workspace / "output").mkdir(parents=True)
            (workspace / "input").mkdir(parents=True)
            project.mkdir()
            (workspace / "requirement.md").write_text("hello", encoding="utf-8")
            (workspace / "input" / "failure-feedback.md").write_text(
                "## Retry Feedback for build\n\n"
                "### Error message to fix\n\n"
                "old failure should not be repeated.\n\n"
                "## Retry Feedback for build\n\n"
                "### Error message to fix\n\n"
                "pytest failed because bubble_sort returned None.\n",
                encoding="utf-8",
            )

            agent = FakeAgent()
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
                "steps": [
                    {
                        "key": "build",
                        "agent": "qwen",
                        "allow_interaction": False,
                        "config": {"compactRetryPromptWhenReusingSession": compact_enabled},
                    }
                ],
            }

            await runner.run(run, "build", "05_build.md", "build-result.md")

            prompt = agent.requests[-1].prompt
            self.assertEqual(prompt.lstrip().startswith("# Compact Reuse Retry"), expected_compact)
            if expected_compact:
                self.assertIn("bubble_sort returned None", prompt)
                self.assertNotIn("old failure should not be repeated", prompt)
                self.assertIn("Continue the same agent session", prompt)
                self.assertIn("real direct project edits", prompt)
                self.assertIn("actual project file diffs", prompt)
            else:
                self.assertIn("test prompt", prompt)

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
