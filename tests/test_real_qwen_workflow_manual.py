from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.runtime_qwen import QwenCliClient
from app.services import workflow_config_service


REQUIRED_SYSTEM_OUTPUTS = {
    "architecture.md": ["##"],
    "reasoning.md": ["##"],
    "spec.md": ["## Goal", "## Scope", "## Acceptance Criteria"],
    "spec-review.md": ["Status:"],
    "todo.md": ["## Todo List", "## Test Plan", "## Done Criteria"],
    "todo-review.md": ["Status:"],
    "test-plan.md": ["FILE:", "END_FILE"],
    "build-reasoning.md": ["##"],
    "build-result.md": ["FILE:", "END_FILE"],
    "test-result.md": ["ExitCode:"],
    "final-review.md": ["Status:"],
}


class Env:
    def __init__(self, **updates: str) -> None:
        self.updates = updates
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        self.old = {key: os.environ.get(key) for key in self.updates}
        os.environ.update(self.updates)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def qwen_bin() -> str:
    return os.environ.get("QWEN_BIN") or ("qwen.cmd" if os.name == "nt" else "qwen")


def require_real_qwen_env(flag: str) -> None:
    if os.environ.get(flag) != "1":
        raise unittest.SkipTest(f"Set {flag}=1 to run this real Qwen manual test.")
    if shutil.which(qwen_bin()) is None:
        raise unittest.SkipTest(f"Qwen CLI not found: {qwen_bin()}")


def wait_for_terminal_run(client: TestClient, run_id: str, timeout_sec: float) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        response = client.get(f"/api/workflow-runs/{run_id}")
        if response.status_code == 200:
            run = response.json()
            if run["status"] in {"done", "failed", "cancelled", "waiting_input"}:
                return run
        time.sleep(0.25)
    raise AssertionError(f"workflow run did not finish within {timeout_sec} seconds")


def assert_file_contains_markers(test_case: unittest.TestCase, path: Path, markers: list[str]) -> None:
    test_case.assertTrue(path.exists(), f"missing artifact: {path}")
    text = path.read_text(encoding="utf-8")
    test_case.assertGreater(len(text.strip()), 10, f"artifact is unexpectedly small: {path}")
    for marker in markers:
        test_case.assertIn(marker, text, f"artifact {path.name} missing marker: {marker}")


class RealQwenFullWorkflowManualTests(unittest.TestCase):
    def test_real_qwen_full_system_workflow_is_opt_in(self) -> None:
        require_real_qwen_env("RUN_REAL_QWEN_FULL")
        timeout_sec = float(os.environ.get("REAL_QWEN_FULL_TIMEOUT_SEC", "900"))
        with tempfile.TemporaryDirectory() as tmp, Env(
            QWEN_MOCK="0",
            QWEN_USE_SERVE=os.environ.get("QWEN_USE_SERVE", "0"),
            QWEN_TIMEOUT_SEC=os.environ.get("QWEN_TIMEOUT_SEC", "300"),
            QWEN_WORKFLOW_SHOW_AGENT_STDOUT="0",
        ):
            project_dir = Path(tmp) / "real-qwen-full-project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Real Qwen Full Workflow Fixture\n", encoding="utf-8")
            (project_dir / "calculator.py").write_text(
                "def add(a, b):\n    return a + b\n",
                encoding="utf-8",
            )
            (project_dir / "tests").mkdir()
            (project_dir / "tests" / "test_calculator.py").write_text(
                "import unittest\n\nfrom calculator import add\n\n\nclass CalculatorTests(unittest.TestCase):\n"
                "    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n\n\nif __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8",
            )

            with TestClient(app) as client:
                session_response = client.post(
                    "/api/sessions",
                    json={"title": "Real Qwen Full", "project_path": str(project_dir)},
                )
                self.assertEqual(session_response.status_code, 200, session_response.text)
                session = session_response.json()
                try:
                    run_response = client.post(
                        f"/api/sessions/{session['id']}/workflow-runs",
                        json={
                            "workflow_id": workflow_config_service.SYSTEM_WORKFLOW_ID,
                            "project_path": str(project_dir),
                            "requirement": "Add a small multiply(a, b) helper to calculator.py and verify it with unittest.",
                            "test_command": "python -m unittest discover -s tests",
                        },
                    )
                    self.assertEqual(run_response.status_code, 200, run_response.text)
                    run = wait_for_terminal_run(client, run_response.json()["id"], timeout_sec)
                    output_dir = Path(run["workspace"]) / "output"
                    for artifact, markers in REQUIRED_SYSTEM_OUTPUTS.items():
                        with self.subTest(artifact=artifact):
                            assert_file_contains_markers(self, output_dir / artifact, markers)
                    self.assertEqual(run["status"], "done", run.get("error"))
                    self.assertTrue(any(step["status"] == "passed" for step in run["steps"]))
                finally:
                    client.delete(f"/api/sessions/{session['id']}")


class RealQwenStabilityManualTests(unittest.TestCase):
    def test_real_qwen_same_prompt_structure_is_stable_across_runs(self) -> None:
        require_real_qwen_env("RUN_REAL_QWEN_STABILITY")
        iterations = int(os.environ.get("REAL_QWEN_STABILITY_RUNS", "3"))
        self.assertGreaterEqual(iterations, 2)
        prompt = """
Return a concise markdown artifact for this requirement.
Requirement: Add a deterministic slugify(text) helper in Python.

Output format must be exactly these markdown sections:
## Goal
## Scope
## Acceptance Criteria

Each section must contain at least one bullet. Do not create files.
""".strip()
        with tempfile.TemporaryDirectory() as tmp, Env(
            QWEN_MOCK="0",
            QWEN_USE_SERVE=os.environ.get("QWEN_USE_SERVE", "0"),
            QWEN_TIMEOUT_SEC=os.environ.get("QWEN_TIMEOUT_SEC", "120"),
        ):
            client = QwenCliClient({"reuse_session": False})
            outputs = [client.run(prompt, Path(tmp), timeout_sec=int(os.environ.get("QWEN_TIMEOUT_SEC", "120"))) for _ in range(iterations)]

        required_sections = ["## Goal", "## Scope", "## Acceptance Criteria"]
        signatures = []
        for output in outputs:
            signatures.append(tuple(section in output for section in required_sections))
            self.assertGreater(len(output.strip()), 30)
        self.assertTrue(all(all(signature) for signature in signatures), f"unstable section signatures: {signatures}")


if __name__ == "__main__":
    unittest.main()
