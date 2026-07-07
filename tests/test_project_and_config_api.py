from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.paths import SETTINGS_FILE
from app.persistence.json_store import Store
from app.workflow_runtime.agents import AgentResult


class ProjectAndConfigApiTests(unittest.TestCase):
    def test_project_message_reset_delete_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client:
            response = client.post("/api/sessions", json={"title": "Lifecycle", "project_path": tmp})
            self.assertEqual(response.status_code, 200, response.text)
            session = response.json()
            original_qwen_session = session["qwen_session_id"]

            message_response = client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"content": "write a sorting helper"},
            )
            self.assertEqual(message_response.status_code, 200, message_response.text)
            messages = client.get(f"/api/sessions/{session['id']}/messages").json()
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0]["kind"], "requirement")

            reset_response = client.post(f"/api/sessions/{session['id']}/reset")
            self.assertEqual(reset_response.status_code, 200, reset_response.text)
            reset_session = reset_response.json()
            self.assertNotEqual(reset_session["qwen_session_id"], original_qwen_session)
            self.assertEqual(client.get(f"/api/sessions/{session['id']}/messages").json(), [])

            delete_response = client.delete(f"/api/sessions/{session['id']}")
            self.assertEqual(delete_response.status_code, 200, delete_response.text)
            sessions = client.get("/api/sessions").json()
            self.assertFalse(any(item["id"] == session["id"] for item in sessions))

    def test_messages_api_returns_chronological_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(
                Path(tmp) / "store.json",
                default_project_path=lambda: tmp,
                default_steps=lambda: [],
            )
            store.save_sync(
                {
                    "sessions": [{"id": "session-order", "title": "Order", "project_path": tmp}],
                    "messages": [
                        {
                            "id": "new",
                            "session_id": "session-order",
                            "role": "user",
                            "kind": "answer",
                            "content": "second",
                            "created_at": "2026-07-01T00:00:02+00:00",
                        },
                        {
                            "id": "old",
                            "session_id": "session-order",
                            "role": "user",
                            "kind": "requirement",
                            "content": "first",
                            "created_at": "2026-07-01T00:00:01+00:00",
                        },
                    ],
                    "runs": [],
                    "workflow_configs": [],
                }
            )
            with TestClient(app) as client, patch("app.runtime_modules.api.store", store):
                response = client.get("/api/sessions/session-order/messages")

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([message["content"] for message in response.json()], ["first", "second"])

    def test_chat_uses_default_agent_resolver(self) -> None:
        class FakeAgent:
            name = "opencode"

            def health(self):
                return {"reuse_session": True}

            async def run_stream(self, request, on_output=None):
                self.request = request
                return AgentResult(output="opencode answer")

        fake_agent = FakeAgent()
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client, patch(
            "app.services.chat_service.runtime.agent_manager.resolve",
            return_value=fake_agent,
        ) as resolve:
            session = client.post("/api/sessions", json={"title": "Chat Agent", "project_path": tmp}).json()
            response = client.post(f"/api/sessions/{session['id']}/chat", json={"content": "hello"})

            self.assertEqual(response.status_code, 200, response.text)
            resolve.assert_called_once_with({"thinking": True, "thinkingLevel": "medium"})
            assistant = response.json()["assistant"]
            self.assertEqual(assistant["content"], "opencode answer")
            self.assertEqual(assistant["trace"]["agent"], "opencode")
            self.assertEqual(assistant["trace"]["prompt_chars"], len("hello"))
            self.assertEqual(assistant["trace"]["output_chars"], len("opencode answer"))
            self.assertGreaterEqual(assistant["trace"]["duration_ms"], 0)
            self.assertEqual(fake_agent.request.session_id, session["id"])
            self.assertEqual(fake_agent.request.prompt, "hello")
            sessions = client.get("/api/sessions").json()
            updated = next(item for item in sessions if item["id"] == session["id"])
            self.assertIsNone(updated["agent_session_ids"]["opencode"])

    def test_chat_repairs_tool_call_json_response_once(self) -> None:
        class FakeAgent:
            name = "opencode"

            def __init__(self) -> None:
                self.requests = []

            def health(self):
                return {"reuse_session": True}

            async def run_stream(self, request, on_output=None):
                self.requests.append(request)
                if len(self.requests) == 1:
                    return AgentResult(output='```json\n{"name":"queryKnowledgebase","arguments":{"prompt":"are you opencode CLI?"}}\n```')
                return AgentResult(output="I am an agent running through OpenCode CLI.")

        fake_agent = FakeAgent()
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client, patch(
            "app.services.chat_service.runtime.agent_manager.resolve",
            return_value=fake_agent,
        ):
            session = client.post("/api/sessions", json={"title": "Chat Repair", "project_path": tmp}).json()
            response = client.post(f"/api/sessions/{session['id']}/chat", json={"content": "are you opencode CLI?"})

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["assistant"]["content"], "I am an agent running through OpenCode CLI.")
            self.assertEqual(len(fake_agent.requests), 2)
            self.assertEqual(fake_agent.requests[0].prompt, "are you opencode CLI?")
            self.assertIn("Do not output JSON", fake_agent.requests[1].prompt)

    def test_chat_prompt_excludes_workflow_requirement_history(self) -> None:
        class FakeAgent:
            name = "opencode"

            def health(self):
                return {"reuse_session": False}

            async def run_stream(self, request, on_output=None):
                self.request = request
                return AgentResult(output="chat answer")

        fake_agent = FakeAgent()
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client, patch(
            "app.services.chat_service.runtime.agent_manager.resolve",
            return_value=fake_agent,
        ):
            session = client.post("/api/sessions", json={"title": "Chat Boundary", "project_path": tmp}).json()
            client.post(f"/api/sessions/{session['id']}/messages", json={"content": "workflow-only requirement"})
            response = client.post(f"/api/sessions/{session['id']}/chat", json={"content": "chat follow up"})

            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("User: chat follow up", fake_agent.request.prompt)
            self.assertNotIn("workflow-only requirement", fake_agent.request.prompt)

    def test_chat_client_request_id_is_idempotent_and_tracks_status(self) -> None:
        class FakeAgent:
            name = "opencode"

            def __init__(self) -> None:
                self.calls = 0

            def health(self):
                return {"reuse_session": True}

            async def run_stream(self, request, on_output=None):
                self.calls += 1
                return AgentResult(output="idempotent answer")

        fake_agent = FakeAgent()
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client, patch(
            "app.services.chat_service.runtime.agent_manager.resolve",
            return_value=fake_agent,
        ):
            session = client.post("/api/sessions", json={"title": "Idempotent Chat", "project_path": tmp}).json()
            body = {"content": "hello once", "clientRequestId": "req-1"}

            first = client.post(f"/api/sessions/{session['id']}/chat", json=body)
            second = client.post(f"/api/sessions/{session['id']}/chat", json=body)

            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(fake_agent.calls, 1)
            self.assertTrue(second.json()["idempotent"])
            messages = client.get(f"/api/sessions/{session['id']}/messages").json()
            chat_messages = [message for message in messages if message.get("client_request_id") == "req-1"]
            self.assertEqual(len(chat_messages), 2)
            self.assertTrue(all(message.get("status") == "completed" for message in chat_messages))

    def test_qwen_config_update_validates_auth_and_clamps_retries(self) -> None:
        original = SETTINGS_FILE.read_text(encoding="utf-8") if SETTINGS_FILE.exists() else ""
        try:
            with TestClient(app) as client:
                bad = client.post("/api/config/qwen", json={"auth_type": "bad-auth"})
                self.assertEqual(bad.status_code, 400)

                good = client.post(
                    "/api/config/qwen",
                    json={"auth_type": "", "reuse_session": True, "max_retries": 999},
                )
                self.assertEqual(good.status_code, 200, good.text)
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
                self.assertTrue(settings["qwen"]["reuse_session"])
                self.assertEqual(settings["qwen"]["max_retries"], 10)

                agent_update = client.post(
                    "/api/config/agents",
                    json={
                        "auth_type": "",
                        "default_agent": "opencode",
                        "opencode_bin": "opencode.cmd",
                        "opencode_mode": "run",
                        "reuse_session": True,
                        "opencode_timeout_sec": 42,
                        "opencode_model": "provider/model",
                        "opencode_agent": "build",
                    },
                )
                self.assertEqual(agent_update.status_code, 200, agent_update.text)
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
                self.assertEqual(settings["agents"]["default"], "opencode")
                self.assertEqual(settings["agents"]["providers"]["opencode"]["bin"], "opencode.cmd")
                self.assertEqual(settings["agents"]["providers"]["opencode"]["mode"], "run")
                self.assertTrue(settings["qwen"]["reuse_session"])
                self.assertTrue(settings["agents"]["providers"]["opencode"]["reuseSession"])
                self.assertEqual(settings["agents"]["providers"]["opencode"]["timeoutSec"], 42)
                self.assertEqual(settings["agents"]["providers"]["opencode"]["model"], "provider/model")
                self.assertEqual(settings["agents"]["providers"]["opencode"]["agent"], "build")

                bad_agent = client.post("/api/config/qwen", json={"default_agent": "missing-agent"})
                self.assertEqual(bad_agent.status_code, 400)
                bad_mode = client.post("/api/config/agents", json={"opencode_mode": "bad-mode"})
                self.assertEqual(bad_mode.status_code, 400)

                legacy_reuse = client.post("/api/config/agents", json={"auth_type": "", "opencode_reuse_session": False})
                self.assertEqual(legacy_reuse.status_code, 200, legacy_reuse.text)
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
                self.assertFalse(settings["agents"]["providers"]["opencode"]["reuseSession"])
        finally:
            if original:
                SETTINGS_FILE.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
