from __future__ import annotations

import json
import time

from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.core.locks import reject_if_chat_busy
from app.core.metrics import metrics
from app.persistence.repositories import store as store_repository
from app.services.agent_session_service import get_agent_session_id, update_agent_session_id
from app.services.agent_execution_service import AgentExecutionService
from app.workflow_runtime.agents import AgentRequest
from app.workflow_runtime.thinking import normalize_thinking_level, thinking_enabled, thinking_label


CHAT_HISTORY_LIMIT = 16
CHAT_RECOVERY_HISTORY_LIMIT = 6
execution_service = AgentExecutionService()


def _chat_thinking_guidance(level: str) -> str:
    normalized = normalize_thinking_level(level, default="none")
    if normalized == "none":
        return ""
    lines = [
        "# Chat Thinking Control",
        "",
        f"Thinking Level: {thinking_label(normalized)} ({normalized})",
        "",
        "Before answering, internally analyze the user message, relevant project context, constraints, and likely failure modes.",
        "Do not expose hidden chain-of-thought. Answer directly, and only include concise assumptions, risks, or validation notes when useful.",
    ]
    if normalized in {"high", "extreme"}:
        lines.extend([
            "",
            "For this answer, internally check whether the request needs code/project awareness, whether previous context changes the answer, and whether the response needs concrete next steps.",
        ])
    if normalized == "extreme":
        lines.extend([
            "",
            "Run an internal Reflect -> Decide pass before finalizing: verify the answer matches the user intent, avoid over-answering, and surface only the final useful result.",
        ])
    return "\n".join(lines).strip()


def _chat_prompt(history: list[dict], content: str, *, reuse_session: bool, thinking_level: str = "none") -> str:
    """Build a normal chat prompt, not a workflow prompt."""
    content = content.strip()
    thinking_guidance = _chat_thinking_guidance(thinking_level)
    if reuse_session:
        return content

    lines: list[str] = []
    if thinking_guidance:
        lines.extend([thinking_guidance, ""])
    recent = history[-CHAT_HISTORY_LIMIT:]
    for message in recent:
        role = "User" if message.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {message.get('content', '').strip()}")
    if lines:
        lines.append("")
    lines.extend([f"User: {content}", "Assistant:"])
    return "\n".join(lines)


def _looks_like_tool_call_json(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("name"), str) and "arguments" in payload


def _chat_repair_prompt(content: str, thinking_level: str = "none") -> str:
    thinking_guidance = _chat_thinking_guidance(thinking_level)
    prefix = f"{thinking_guidance}\n\n" if thinking_guidance else ""
    return (
        prefix
        + "Please answer the user directly in natural language. "
        "Do not output JSON, tool calls, or markdown code blocks.\n\n"
        f"User question: {content.strip()}"
    )


def _chat_recovery_prompt(history: list[dict], content: str, thinking_level: str = "none") -> str:
    lines = [
        "Continue this chat after automatic context/session recovery.",
        "Use only the compact context below and answer the latest user message directly.",
        "Do not explain the recovery process unless the user asks.",
        "",
    ]
    guidance = _chat_thinking_guidance(thinking_level)
    if guidance:
        lines.extend([guidance, ""])
    for message in history[-CHAT_RECOVERY_HISTORY_LIMIT:]:
        role = "User" if message.get("role") == "user" else "Assistant"
        text = str(message.get("content") or "").strip()
        if text:
            lines.append(f"{role}: {text[:2000]}")
    lines.extend(["", f"Latest User: {content.strip()}", "Assistant:"])
    return "\n".join(lines)


async def chat(session_id: str, body: runtime.CreateMessageRequest) -> dict:
    data = await store_repository.read()
    session = next((item for item in data["sessions"] if item["id"] == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    client_request_id = (body.client_request_id or "").strip() or None
    if client_request_id:
        existing_user = next(
            (
                msg
                for msg in data.get("messages", [])
                if msg.get("session_id") == session_id
                and msg.get("kind") == "chat"
                and msg.get("client_request_id") == client_request_id
                and msg.get("role") == "user"
            ),
            None,
        )
        existing_assistant = next(
            (
                msg
                for msg in data.get("messages", [])
                if msg.get("session_id") == session_id
                and msg.get("kind") == "chat"
                and msg.get("client_request_id") == client_request_id
                and msg.get("role") == "assistant"
            ),
            None,
        )
        if existing_user and existing_assistant:
            return {"user": existing_user, "assistant": existing_assistant, "idempotent": True}

    history = [
        msg
        for msg in data["messages"]
        if msg["session_id"] == session_id and msg.get("kind") == "chat"
    ]
    async with reject_if_chat_busy(session_id):
        user_msg = await runtime.append_session_message(
            session_id,
            "user",
            body.content,
            kind="chat",
            client_request_id=client_request_id,
            status="completed",
        )
        assistant_msg = await runtime.append_session_message(
            session_id,
            "assistant",
            "",
            kind="chat",
            client_request_id=client_request_id,
            status="pending",
        )
        project_path = runtime.resolve_project_path(session.get("project_path"), runtime.ROOT)
        chat_started = time.perf_counter()

        try:
            await runtime.update_message(assistant_msg["id"], status="running")
            thinking_level = normalize_thinking_level(body.thinking_level, default="medium")
            agent = runtime.agent_manager.resolve({
                "thinking": thinking_enabled(thinking_level),
                "thinkingLevel": thinking_level,
            })
            agent_health = agent.health()
            reuse_session = bool(agent_health.get("reuse_session"))
            prompt = _chat_prompt(history, body.content, reuse_session=reuse_session, thinking_level=thinking_level)
            session_decision = execution_service.session_manager.resolve(
                session,
                step_key="chat",
                agent=agent.name,
            )
            agent_session_id = session_decision.session_id or get_agent_session_id(session, agent.name, session_id)
            repaired_tool_call = False
            chat_stream_id = f"chat-{session_id}"

            async def publish_chat_output(stream: str, text: str) -> None:
                if not text:
                    return
                if stream == "status":
                    await runtime.bus.publish(
                        chat_stream_id,
                        {"type": "agent_status", "agent": agent.name, "step": "chat", "message": text},
                    )
                    return
                await runtime.bus.publish(
                    chat_stream_id,
                    {"type": "agent_output", "agent": agent.name, "step": "chat", "stream": stream, "text": text},
                )

            await runtime.bus.publish(
                chat_stream_id,
                {"type": "agent_status", "agent": agent.name, "step": "chat", "message": f"{agent.name} is running..."},
            )
            request = AgentRequest(
                    run_id=f"chat-{session_id}",
                    step_key="chat",
                    prompt=prompt,
                    cwd=project_path,
                    session_id=agent_session_id,
                )
            outcome = await execution_service.execute(
                agent,
                request,
                on_output=publish_chat_output,
                on_status=lambda message: publish_chat_output("status", message),
                recovery_prompt_factory=lambda _failure, _request, _attempt: _chat_recovery_prompt(history, body.content, thinking_level),
            )
            result = outcome.result
            if result.session_id != agent_session_id:
                await update_agent_session_id(session_id, agent.name, result.session_id)
            answer = result.output
            if _looks_like_tool_call_json(answer):
                repaired_tool_call = True
                repair_outcome = await execution_service.execute(
                    agent,
                    AgentRequest(
                        run_id=f"chat-{session_id}-repair",
                        step_key="chat",
                        prompt=_chat_repair_prompt(body.content, thinking_level),
                        cwd=project_path,
                        session_id=result.session_id,
                    ),
                    on_output=publish_chat_output,
                    on_status=lambda message: publish_chat_output("status", message),
                )
                repair_result = repair_outcome.result
                if repair_result.session_id != result.session_id:
                    await update_agent_session_id(session_id, agent.name, repair_result.session_id)
                answer = repair_result.output
        except Exception as exc:
            metrics.increment("chat.failed")
            await runtime.update_message(
                assistant_msg["id"],
                content=f"Chat failed: {exc}",
                status="failed",
                error=str(exc),
                trace={
                    "agent": locals().get("agent").name if "agent" in locals() else "",
                    "duration_ms": int((time.perf_counter() - chat_started) * 1000),
                    "error": str(exc),
                },
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        completed = await runtime.update_message(
            assistant_msg["id"],
            content=answer.strip() or "(Agent returned no text.)",
            status="completed",
            trace={
                "agent": agent.name,
                "provider_health": {key: agent_health.get(key) for key in ["type", "mock", "reuse_session", "timeout_sec", "exists"]},
                "session_reused": bool(agent_session_id),
                "agent_session_id": result.session_id,
                "prompt_chars": len(prompt),
                "output_chars": len(answer or ""),
                "duration_ms": int((time.perf_counter() - chat_started) * 1000),
                "repaired_tool_call": repaired_tool_call,
                "thinking_level": thinking_level,
                "agent_attempts": outcome.attempts,
                "recoveries": outcome.recoveries,
            },
        )
        await runtime.bus.publish(
            f"chat-{session_id}",
            {"type": "done", "agent": agent.name, "step": "chat", "message": "Chat completed."},
        )
        return {"user": user_msg, "assistant": completed or assistant_msg}
