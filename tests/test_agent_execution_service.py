from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from app.runtime_modules.errors import WorkflowError
from app.services.agent_execution_service import AgentExecutionPolicy, AgentExecutionService
from app.workflow.agents import AgentCapabilities, AgentRequest, AgentResult
from app.workflow.agents.errors import classify_agent_error


class ScriptedAgent:
    name = "scripted"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[AgentRequest] = []

    async def run_stream(self, request, on_output=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return AgentResult(output=outcome, session_id=request.session_id)

    def classify_error(self, error):
        return classify_agent_error(error)

    def capabilities(self):
        return AgentCapabilities(session_resume=True)

    def health(self):
        return {"exists": True}

    def command_preview(self, request):
        return "scripted"


class AgentExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    def request(self, *, session_id="session-1") -> AgentRequest:
        return AgentRequest(run_id="run-1", step_key="build", prompt="do work", cwd=Path.cwd(), session_id=session_id)

    async def test_transient_api_failure_retries_same_session_with_backoff_policy(self) -> None:
        agent = ScriptedAgent([WorkflowError("HTTP 503 service unavailable"), "done"])
        statuses: list[str] = []
        outcome = await AgentExecutionService().execute(
            agent,
            self.request(),
            on_status=lambda message: self._append(statuses, message),
            policy=AgentExecutionPolicy(max_transient_retries=2, base_backoff_seconds=0),
        )
        self.assertEqual(outcome.result.output, "done")
        self.assertEqual(outcome.attempts, 2)
        self.assertEqual(agent.requests[1].session_id, "session-1")
        self.assertEqual(outcome.recoveries[0]["code"], "TRANSIENT_API_FAILURE")
        self.assertTrue(statuses)

    async def test_context_limit_uses_compact_handoff_and_fresh_session(self) -> None:
        agent = ScriptedAgent([WorkflowError("maximum context limit reached"), "recovered"])
        outcome = await AgentExecutionService().execute(
            agent,
            self.request(),
            recovery_prompt_factory=lambda _failure, _request, _attempt: "compact handoff",
            policy=AgentExecutionPolicy(max_transient_retries=2, base_backoff_seconds=0),
        )
        self.assertEqual(agent.requests[1].prompt, "compact handoff")
        self.assertIsNone(agent.requests[1].session_id)
        self.assertTrue(outcome.recoveries[0]["fresh_session"])

    async def test_empty_output_is_retried_but_auth_failure_stops(self) -> None:
        recovered = ScriptedAgent(["", "answer"])
        outcome = await AgentExecutionService().execute(
            recovered,
            self.request(),
            policy=AgentExecutionPolicy(max_transient_retries=1, base_backoff_seconds=0),
        )
        self.assertEqual(outcome.result.output, "answer")

        denied = ScriptedAgent([WorkflowError("401 unauthorized"), "must not run"])
        with self.assertRaisesRegex(WorkflowError, "401"):
            await AgentExecutionService().execute(
                denied,
                self.request(),
                policy=AgentExecutionPolicy(max_transient_retries=3, base_backoff_seconds=0),
            )
        self.assertEqual(len(denied.requests), 1)

    async def test_cancellation_is_never_retried(self) -> None:
        agent = ScriptedAgent([asyncio.CancelledError(), "must not run"])
        with self.assertRaises(asyncio.CancelledError):
            await AgentExecutionService().execute(agent, self.request())
        self.assertEqual(len(agent.requests), 1)

    @staticmethod
    async def _append(items: list[str], value: str) -> None:
        items.append(value)


if __name__ == "__main__":
    unittest.main()
