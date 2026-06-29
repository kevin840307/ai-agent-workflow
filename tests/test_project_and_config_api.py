from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_modules.paths import SETTINGS_FILE
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
                json={"content": "請做一個測試需求"},
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

    def test_chat_uses_default_agent_resolver(self) -> None:
        class FakeAgent:
            name = "opencode"

            async def run_stream(self, request, on_output=None):
                self.request = request
                return AgentResult(output="opencode answer")

        fake_agent = FakeAgent()
        with tempfile.TemporaryDirectory() as tmp, TestClient(app) as client, patch(
            "app.services.project_service.runtime.agent_manager.resolve",
            return_value=fake_agent,
        ) as resolve:
            session = client.post("/api/sessions", json={"title": "Chat Agent", "project_path": tmp}).json()
            response = client.post(f"/api/sessions/{session['id']}/chat", json={"content": "hello"})

            self.assertEqual(response.status_code, 200, response.text)
            resolve.assert_called_once_with()
            self.assertEqual(response.json()["assistant"]["content"], "opencode answer")
            self.assertEqual(fake_agent.request.session_id, session["id"])

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
                    },
                )
                self.assertEqual(agent_update.status_code, 200, agent_update.text)
                settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
                self.assertEqual(settings["agents"]["default"], "opencode")
                self.assertEqual(settings["agents"]["providers"]["opencode"]["bin"], "opencode.cmd")
                self.assertEqual(settings["agents"]["providers"]["opencode"]["mode"], "run")

                bad_agent = client.post("/api/config/qwen", json={"default_agent": "missing-agent"})
                self.assertEqual(bad_agent.status_code, 400)
                bad_mode = client.post("/api/config/agents", json={"opencode_mode": "bad-mode"})
                self.assertEqual(bad_mode.status_code, 400)
        finally:
            if original:
                SETTINGS_FILE.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
