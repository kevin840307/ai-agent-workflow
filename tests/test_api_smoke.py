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
                "/ai-workflow-assets",
                "/health",
                "/ready",
                "/metrics",
                "/api/config",
                "/api/workflows",
                "/api/workflows/functions",
                "/api/workflow-assets",
                "/api/sessions",
            ]:
                response = client.get(path)
                self.assertLess(response.status_code, 400, f"{path}: {response.text[:500]}")

    def test_workflow_functions_api_includes_consensus_agent(self) -> None:
        with TestClient(app) as client:
            payload = client.get("/api/workflows/functions").json()

        function_ids = {item["id"] for item in payload.get("functions", [])}
        self.assertIn("consensus_agent", function_ids)
        self.assertIn("validate_spec", function_ids)
        self.assertIn("run_pytest", function_ids)
        self.assertEqual(len(payload.get("reviewStrategies", [])), 3)
        self.assertEqual(len(payload.get("aggregators", [])), 3)

    def test_error_payload_is_consistent(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/workflow-runs/missing-run")

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "HTTP_404")
        self.assertEqual(payload["detail"], payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
