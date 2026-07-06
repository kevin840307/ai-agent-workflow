from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.workflow_runtime.trace import build_run_trace, render_gate_report


class ControllerObservabilityAndManualControlTests(unittest.TestCase):
    def test_trace_includes_gate_report_and_step_prompt_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / ".workflow").mkdir()
            (run_dir / "prompts").mkdir()
            (run_dir / "output").mkdir()
            (run_dir / ".workflow" / "run-log.md").write_text(
                "[now] auto_generation/TASK-001: accepted direct agent edit(s): sort_utils.py, tests/test_sort.py\n",
                encoding="utf-8",
            )
            (run_dir / "prompts" / "auto_generation.md").write_text("raw", encoding="utf-8")
            (run_dir / "prompts" / "auto_generation.effective.md").write_text("effective prompt", encoding="utf-8")
            (run_dir / "prompts" / "auto_generation.prompt-meta.json").write_text("{}", encoding="utf-8")
            run = {
                "id": "run-1",
                "session_id": "session-1",
                "status": "done",
                "workflow_id": "adaptive-auto-workflow",
                "workflow_name": "Adaptive Auto Workflow",
                "workspace": str(run_dir),
                "project_path": str(run_dir / "project"),
                "steps": [
                    {"key": "auto_generation", "title": "Execute", "type": "ai", "status": "passed", "config": {}},
                    {"key": "ai_review", "title": "Review", "type": "review", "status": "passed", "config": {}},
                ],
                "artifacts": [],
                "timeline": [],
            }
            trace = build_run_trace(run, run_dir)
            step = next(item for item in trace["steps"] if item["key"] == "auto_generation")
            self.assertEqual(step["effective_prompt_chars"], len("effective prompt"))
            self.assertIn("sort_utils.py", step["changed_files"])
            report = render_gate_report(trace)
            self.assertIn("# Gate Report", report)
            self.assertIn("Status: PASS", report)
            self.assertIn("sort_utils.py", report)

    def test_manual_step_control_endpoints_are_available(self) -> None:
        previous_mock = os.environ.get("QWEN_MOCK")
        os.environ["QWEN_MOCK"] = "1"
        os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
        try:
            ctx = TemporaryDirectory()
            tmp = ctx.__enter__()
            client_ctx = TestClient(app)
            client = client_ctx.__enter__()
            project = Path(tmp) / "project"
            project.mkdir()
            session = client.post("/api/sessions", json={"title": "manual", "project_path": str(project)}).json()
            run_resp = client.post(
                f"/api/sessions/{session['id']}/workflow-runs",
                json={
                    "workflow_id": "adaptive-auto-workflow",
                    "project_path": str(project),
                    "requirement": "Create a tiny helper.",
                },
            )
            self.assertLess(run_resp.status_code, 400, run_resp.text)
            run = run_resp.json()
            term = client.post(f"/api/workflow-runs/{run['id']}/terminate")
            self.assertLess(term.status_code, 400, term.text)
            skip = client.post(f"/api/workflow-runs/{run['id']}/steps/skip", json={"step_key": "generate_task_prompts", "reason": "manual test"})
            self.assertLess(skip.status_code, 400, skip.text)
            skipped = skip.json()
            first = next(step for step in skipped["steps"] if step["key"] == "generate_task_prompts")
            self.assertEqual(first["status"], "skipped")
            mark = client.post(f"/api/workflow-runs/{run['id']}/steps/pass", json={"step_key": "generate_task_prompts", "reason": "manual pass"})
            self.assertLess(mark.status_code, 400, mark.text)
            passed = mark.json()
            first = next(step for step in passed["steps"] if step["key"] == "generate_task_prompts")
            self.assertEqual(first["status"], "passed")
        finally:
            try:
                client_ctx.__exit__(None, None, None)
                ctx.__exit__(None, None, None)
            except Exception:
                pass
            if previous_mock is None:
                os.environ.pop("QWEN_MOCK", None)
            else:
                os.environ["QWEN_MOCK"] = previous_mock

    def test_runner_ui_exposes_observability_and_manual_controls(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
        css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
        designer_html = (root / "static/workflow-designer.html").read_text(encoding="utf-8")
        real_smoke = (root / "scripts/run_real_agent_smoke.py").read_text(encoding="utf-8")

        for marker in ["Gate Report", "Effective", "Prompt Meta", "Resume", "Skip", "Mark Pass", "manualStepControl", "steps/${endpoint}", "/resume"]:
            with self.subTest(marker=marker):
                self.assertIn(marker, runs)
        self.assertIn("run-timeline-inline", css)
        self.assertIn("Controller UX", designer_html)
        self.assertIn("Every N failures escalate", designer_html)
        self.assertIn("Run a manually-triggered real Qwen/OpenCode smoke", real_smoke)
        self.assertIn("Refusing to run real-agent smoke while QWEN_MOCK=1", real_smoke)


if __name__ == "__main__":
    unittest.main()
