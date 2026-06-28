from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_paths import SETTINGS_FILE


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
        finally:
            if original:
                SETTINGS_FILE.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
