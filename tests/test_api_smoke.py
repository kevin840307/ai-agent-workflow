from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiSmokeTests(unittest.TestCase):
    def test_main_pages_and_core_api_load(self) -> None:
        with TestClient(app) as client:
            for path in [
                "/",
                "/workflow-designer",
                "/api/config",
                "/api/workflows",
                "/api/workflows/functions",
                "/api/sessions",
            ]:
                response = client.get(path)
                self.assertLess(response.status_code, 400, f"{path}: {response.text[:500]}")

    def test_workflow_functions_api_includes_consensus_agent(self) -> None:
        with TestClient(app) as client:
            payload = client.get("/api/workflows/functions").json()

        validator_ids = {item["id"] for item in payload.get("validators", [])}
        self.assertIn("consensus_agent", validator_ids)
        self.assertIn("validate_spec", validator_ids)
        self.assertIn("run_pytest", validator_ids)
        self.assertEqual(len(payload.get("reviewStrategies", [])), 3)
        self.assertEqual(len(payload.get("aggregators", [])), 3)


if __name__ == "__main__":
    unittest.main()
