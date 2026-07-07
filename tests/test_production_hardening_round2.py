from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from app.stores import FileRunStore, FileStepStore
from app.workflow_runtime.event_log import append_event, read_events, summarize_events
from app.workflow_runtime.agent_safety import build_agent_safety_report, write_agent_safety_report
from app.services.workflow_asset_validator import validate_all_workflows, validate_workflow


def test_file_run_store_transition_and_step_mark_keep_state_consistent() -> None:
    data = {
        "runs": [
            {
                "id": "run-1",
                "session_id": "s1",
                "status": "queued",
                "steps": [{"key": "build", "status": "pending"}],
            }
        ]
    }

    async def read():
        return data

    async def mutate(fn):
        return fn(data)

    async def scenario():
        run_store = FileRunStore(read=read, mutate=mutate)
        step_store = FileStepStore(run_store)
        await run_store.transition_status("run-1", "running")
        await step_store.mark("run-1", "build", "running")
        await step_store.mark("run-1", "build", "passed")
        await run_store.transition_status("run-1", "done", ended=True)
        return await run_store.get("run-1"), await step_store.get("run-1", "build")

    run, step = asyncio.run(scenario())
    assert run["status"] == "done"
    assert run["error"] is None
    assert run["ended_at"]
    assert step["status"] == "passed"
    assert step["started_at"]
    assert step["ended_at"]


def test_workflow_events_jsonl_roundtrip(tmp_path: Path) -> None:
    run = {"id": "run-events", "workspace": str(tmp_path)}
    append_event(run, "run.started", message="started", status="running")
    append_event(run, "step.started", step_key="build", message="build started")
    events = read_events(run)
    assert [event["type"] for event in events] == ["run.started", "step.started"]
    assert events[1]["step_key"] == "build"
    summary = summarize_events(run)
    assert summary["event_count"] == 2
    assert summary["counts"]["run.started"] == 1


def test_agent_safety_report_flags_scope_and_secret_like_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    workspace = tmp_path / "workspace"
    (workspace / ".workflow").mkdir(parents=True)
    (workspace / ".workflow" / "project-snapshot-before.json").write_text("{}", encoding="utf-8")
    (project / ".env.example").write_text("TOKEN=example", encoding="utf-8")
    run = {
        "id": "run-safety",
        "workflow_id": "wf",
        "agent": "qwen",
        "status": "done",
        "workspace": str(workspace),
        "project_path": str(project),
        "patch_mode": "review",
    }
    report = write_agent_safety_report(run)
    assert report["schema"] == "aiwf.agent-safety-report.v1"
    assert report["cwd"] == str(project)
    assert report["risk"] in {"low", "medium", "high"}
    assert (workspace / ".workflow" / "artifacts" / "reports" / "agent-safety-report.md").exists()
    assert (workspace / ".workflow" / "artifacts" / "reports" / "agent-safety-report.json").exists()


def test_workflow_asset_validator_reports_errors_for_bad_workflow() -> None:
    result = validate_workflow(
        {
            "id": "bad",
            "steps": [
                {"key": "build", "type": "python", "functions": ["missing_function"], "retryFromStepKey": "nope"},
                {"key": "build", "type": "ai"},
            ],
        }
    )
    assert result["error_count"] >= 2
    messages = "\n".join(issue["message"] for issue in result["issues"])
    assert "Duplicate step key" in messages
    assert "Unknown" in messages


def test_repository_workflow_assets_validate_without_errors() -> None:
    result = asyncio.run(validate_all_workflows())
    assert result["schema"] == "aiwf.workflow-validator.v3"
    assert result["ok"] is True
    assert result["workflow_count"] >= 3


def test_ui_empty_state_contract_present() -> None:
    dom = Path("static/js/core/dom.js").read_text(encoding="utf-8")
    runs = Path("static/js/features/runs.js").read_text(encoding="utf-8")
    css = Path("static/css/workflow-runner.css").read_text(encoding="utf-8")
    assert "emptyState(" in dom
    assert "safeText(" in dom
    assert "No run selected" in runs
    assert ".ui-empty-state" in css
    assert "No run selected" in runs


def test_validate_workflow_assets_script_passes() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/validate_workflow_assets.py"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "status: PASS" in proc.stdout


def test_soak_test_script_has_safe_defaults() -> None:
    text = Path("scripts/run_soak_test.py").read_text(encoding="utf-8")
    assert "aiwf.soak-test.v1" in text
    assert "project_lock_leftover" in text
    assert "run_self_prompt_workflow_e2e.py" in text
