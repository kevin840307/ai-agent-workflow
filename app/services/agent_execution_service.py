from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import WorkflowError
from app.core.provider_slots import provider_execution_slot
from app.services.agent_session_manager import AgentSessionManager
from app.workflow.agents import AgentClient, AgentOutputCallback, AgentRequest, AgentResult
from app.workflow.agents.errors import classify_agent_error
from app.services.model_circuit_breaker import model_circuit_breaker, provider_circuit_key


RecoveryPromptFactory = Callable[[dict[str, Any], AgentRequest, int], str | Awaitable[str]]
StatusCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class AgentExecutionPolicy:
    max_transient_retries: int = 3
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0
    retry_empty_output: bool = True
    fresh_session_on_timeout: bool = True


@dataclass(slots=True)
class AgentExecutionOutcome:
    result: AgentResult
    request: AgentRequest
    attempts: int
    recoveries: list[dict[str, Any]] = field(default_factory=list)


class AgentExecutionService:
    """One resilient execution path for chat and every workflow entry point."""

    def __init__(self, *, session_manager: AgentSessionManager | None = None) -> None:
        self.session_manager = session_manager or AgentSessionManager()

    @staticmethod
    def default_policy() -> AgentExecutionPolicy:
        return AgentExecutionPolicy(
            max_transient_retries=max(0, int(os.environ.get("AIWF_AGENT_TRANSIENT_RETRIES", "3") or 3)),
            base_backoff_seconds=max(0.0, float(os.environ.get("AIWF_AGENT_RETRY_BACKOFF_SEC", "0.5") or 0.5)),
            max_backoff_seconds=max(0.0, float(os.environ.get("AIWF_AGENT_MAX_BACKOFF_SEC", "8") or 8)),
        )

    async def execute(
        self,
        agent: AgentClient,
        request: AgentRequest,
        *,
        on_output: AgentOutputCallback | None = None,
        on_status: StatusCallback | None = None,
        policy: AgentExecutionPolicy | None = None,
        recovery_prompt_factory: RecoveryPromptFactory | None = None,
    ) -> AgentExecutionOutcome:
        policy = policy or self.default_policy()
        current = request
        recoveries: list[dict[str, Any]] = []
        attempts = 0

        circuit_key = provider_circuit_key(agent, request)
        while True:
            circuit = await model_circuit_breaker.allow(circuit_key)
            if not circuit.get("allowed"):
                wait_seconds = max(0.25, min(float(circuit.get("retry_after_sec") or 1.0), 5.0))
                if on_status:
                    await on_status(f"{agent.name} model circuit is open; waiting {wait_seconds:.1f}s before a health probe...")
                await asyncio.sleep(wait_seconds)
                continue
            attempts += 1
            try:
                async with provider_execution_slot(circuit_key):
                    result = await agent.run_stream(current, on_output=on_output)
                await model_circuit_breaker.record_success(circuit_key)
                if result.output and result.output.strip():
                    return AgentExecutionOutcome(result=result, request=current, attempts=attempts, recoveries=recoveries)
                if not policy.retry_empty_output:
                    return AgentExecutionOutcome(result=result, request=current, attempts=attempts, recoveries=recoveries)
                raise WorkflowError(f"{agent.name} returned empty output")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = self._classify(agent, exc)
                code = str(failure.get("code") or "AGENT_ERROR")
                transient = code in {"TRANSIENT_API_FAILURE", "AGENT_TIMEOUT"}
                circuit_state = await model_circuit_breaker.record_failure(circuit_key, exc, transient=transient)
                retry_index = len(recoveries) + 1
                if not failure.get("recoverable") or retry_index > policy.max_transient_retries:
                    raise

                strategy = str(failure.get("strategy") or "retry")
                fresh_session = strategy in {"create", "handoff_fresh_session", "fresh_session"}
                if code == "AGENT_TIMEOUT" and not policy.fresh_session_on_timeout:
                    fresh_session = False
                next_prompt = current.prompt
                if recovery_prompt_factory and strategy == "handoff_fresh_session":
                    generated = recovery_prompt_factory(failure, current, retry_index)
                    next_prompt = await generated if hasattr(generated, "__await__") else generated
                metadata = dict(current.metadata or {})
                metadata.update(
                    {
                        "recovery_code": code,
                        "recovery_strategy": strategy,
                        "recovery_attempt": retry_index,
                        "recovered_from_session_id": current.session_id,
                    }
                )
                current = replace(
                    current,
                    prompt=str(next_prompt),
                    session_id=None if fresh_session else current.session_id,
                    metadata=metadata,
                )
                delay = 0.0 if fresh_session else min(
                    policy.max_backoff_seconds,
                    policy.base_backoff_seconds * (2 ** max(0, retry_index - 1)),
                )
                recovery = {
                    "attempt": retry_index,
                    "code": code,
                    "strategy": strategy,
                    "fresh_session": fresh_session,
                    "backoff_seconds": delay,
                    "error": str(exc)[:1000],
                    "circuit": circuit_state,
                }
                recoveries.append(recovery)
                if on_status:
                    await on_status(self._status_message(agent.name, recovery))
                if code == "TRANSIENT_API_FAILURE" and bool((current.metadata or {}).get("unattended")):
                    from app.services.provider_connectivity_service import wait_for_connectivity
                    connectivity = await wait_for_connectivity(
                        current.cwd,
                        str((current.metadata or {}).get("agent") or agent.name),
                        on_status=on_status,
                    )
                    recovery["connectivity_wait"] = connectivity
                    if connectivity.get("state") == "online":
                        delay = 0.0
                if delay > 0:
                    await asyncio.sleep(delay)

    @staticmethod
    def _classify(agent: AgentClient, error: Exception) -> dict[str, Any]:
        classifier = getattr(agent, "classify_error", None)
        result = classifier(error) if callable(classifier) else classify_agent_error(error)
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _status_message(agent_name: str, recovery: dict[str, Any]) -> str:
        code = recovery.get("code")
        if recovery.get("fresh_session"):
            return f"{agent_name} connection/session recovered; continuing in a fresh session..."
        if recovery.get("backoff_seconds"):
            return f"{agent_name} API was temporarily unavailable ({code}); retrying automatically..."
        return f"{agent_name} recovered from {code}; continuing..."


__all__ = [
    "AgentExecutionOutcome",
    "AgentExecutionPolicy",
    "AgentExecutionService",
]
