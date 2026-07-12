from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.main import app
from app.persistence.sqlite_store import SQLiteStore
from app.services.agent_session_manager import AgentSessionManager
from app.services.run_overview_service import build_run_overview
from app.services.optimization_service import recommend_execution
from app.services.setup_service import setup_status, setup_smoke_test
from app.workflow_engine.state_machine import InvalidTransition, append_transition, validate_transition
from app.workflow_runtime.artifact_policy import compact_run_diagnostics, filter_artifacts
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.run_artifacts import read_run_artifact_index
from app.workflow_runtime.run_lifecycle import build_restart_recovery, mark_stale_active_run_interrupted
from app.workflow_runtime.recovery_counters import increment_recovery_counter, public_recovery_counters, reset_consecutive_failures


def test_state_machine_records_valid_transitions_and_rejects_invalid() -> None:
    record: dict[str, Any] = {}
    assert validate_transition("run", "queued", "running").allowed
    append_transition(record, kind="run", source="queued", target="running", reason="worker started")
    assert record["transitions"][-1]["reason"] == "worker started"
    with pytest.raises(InvalidTransition):
        validate_transition("run", "cancelled", "waiting_input")


def test_agent_session_manager_uses_distinct_roles_and_fresh_policy() -> None:
    manager = AgentSessionManager()
    run = {
        "qwen_session_id": "shared",
        "agent_session_ids": {"qwen": "shared"},
        "role_session_ids": {"build": {"qwen": "build-session"}, "review": {"qwen": "review-session"}},
        "steps": [
            {"key": "build", "config": {"sessionRole": "build"}},
            {"key": "ai_review", "config": {"sessionRole": "review"}},
        ],
    }
    assert manager.resolve(run, step_key="build", agent="qwen").session_id == "build-session"
    assert manager.resolve(run, step_key="ai_review", agent="qwen").session_id == "review-session"
    fresh = manager.resolve(run, step_key="ai_review", agent="qwen", fresh=True)
    assert fresh.fresh and fresh.session_id is None and fresh.role == "review"
    manager.record(run, role="validation", agent="qwen", session_id="validation-session")
    assert run["role_session_ids"]["validation"]["qwen"] == "validation-session"


def test_sqlite_store_v2_projects_structured_run_data_and_backup(tmp_path: Path) -> None:
    db = tmp_path / "store.sqlite3"
    store = SQLiteStore(db, default_project_path=lambda: str(tmp_path), default_steps=lambda: [])
    run = {
        "id": "run-v8",
        "session_id": "session-v8",
        "workflow_id": "general-auto-development",
        "workflow_name": "General",
        "project_path": str(tmp_path),
        "status": "running",
        "phase": "executing",
        "steps": [{"key": "build", "title": "Build", "status": "passed", "retry_count": 1}],
        "tasks": [{"id": "TASK-001", "title": "Implement", "status": "done"}],
        "role_session_ids": {"build": {"qwen": "qwen-build"}},
        "events": [{"step_key": "build", "type": "passed", "message": "done", "at": "2026-07-11T00:00:00+00:00"}],
        "artifacts": [{"id": "final", "path": "reports/final-report.md", "role": "final-report", "visibility": "essential"}],
        "validation_results": [{"key": "pytest", "status": "passed", "command": ["python", "-m", "pytest"], "exit_code": 0}],
        "file_changes": [{"path": "sort.py", "status": "added", "additions": 10, "deletions": 0}],
        "checkpoints": [{"id": "step-build-1", "step_key": "build", "status": "passed", "created_at": "2026-07-11T00:00:00+00:00"}],
        "project_lock": {"project_path": str(tmp_path), "run_id": "run-v8", "mode": "write", "created_at": "2026-07-11T00:00:00+00:00"},
    }
    store.save_sync({"sessions": [], "messages": [], "workflow_configs": [], "runs": [run]})
    counts = store.projection_counts()
    for table in ("runs", "run_steps", "tasks", "agent_sessions", "run_events", "run_artifacts", "validation_results", "file_changes", "checkpoints", "project_locks"):
        assert counts[table] >= 1, table
    projection = store.query_run_projection("run-v8")
    assert projection["run"]["status"] == "running"
    assert projection["steps"][0]["step_key"] == "build"
    assert projection["validations"][0]["command"] == "python -m pytest"
    backup = store.backup_sync()
    assert backup.is_file() and backup.stat().st_size > 0
    with sqlite3.connect(backup) as conn:
        assert conn.execute("select count(*) from runs").fetchone()[0] == 1


def test_compact_artifacts_keep_only_user_results_and_one_diagnostic_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIWF_ARTIFACT_MODE", "compact")
    run_dir = tmp_path / "run"
    (run_dir / ".workflow").mkdir(parents=True)
    (run_dir / "prompts").mkdir()
    (run_dir / "output").mkdir()
    (run_dir / ".workflow" / "run-log.md").write_text("verbose log", encoding="utf-8")
    (run_dir / ".workflow" / "state.json").write_text("{}", encoding="utf-8")
    (run_dir / "prompts" / "build.md").write_text("large prompt", encoding="utf-8")
    (run_dir / "output" / "test-result.md").write_text("Status: PASS", encoding="utf-8")
    run = {"id": "r", "session_id": "s", "workflow_id": "general-auto-development", "status": "done", "workspace": str(run_dir), "project_path": str(tmp_path), "steps": [{"key": "build", "status": "passed", "retry_count": 0}]}
    index = read_run_artifact_index(run)
    paths = {item["path"] for item in index["records"]}
    assert index["artifact_mode"] == "compact"
    assert "validation/test-result.md" in paths
    assert "reports/final-report.md" in paths
    assert not any(path.startswith("steps/") for path in paths)
    assert not (run_dir / ".workflow" / "artifacts" / "README.md").exists()
    assert not (run_dir / ".workflow" / "artifacts" / "console").exists()
    result = compact_run_diagnostics(run)
    assert result["compacted"] and result["file_count"] >= 3
    assert (run_dir / ".workflow" / "artifacts" / "diagnostics.zip").is_file()
    essential = filter_artifacts(index["records"], "essential")
    assert all(item["visibility"] == "essential" for item in essential)


def test_restart_recovery_and_overview_prioritize_checkpoint_resume(tmp_path: Path) -> None:
    run = {
        "id": "recover",
        "status": "failed",
        "error": "server restarted",
        "error_code": "INTERRUPTED",
        "restart_recoverable": True,
        "workspace": str(tmp_path),
        "project_path": str(tmp_path),
        "workflow_id": "general-auto-development",
        "steps": [
            {"key": "plan_tasks", "status": "passed", "retry_count": 0},
            {"key": "build", "status": "failed", "retry_count": 0},
            {"key": "run_test", "status": "pending", "retry_count": 0},
        ],
        "checkpoints": [{"id": "step-plan_tasks-1", "step_key": "plan_tasks", "status": "passed"}],
    }
    run["recovery"] = build_restart_recovery(run)
    overview = build_run_overview(run)
    assert run["recovery"]["resume_index"] == 1
    assert overview["recommended_actions"][0]["id"] == "resume"
    assert overview["recovery"]["checkpoint_id"] == "step-plan_tasks-1"


def test_failure_classifier_exposes_user_friendly_zh_tw_message() -> None:
    result = classify_failure("pytest import file mismatch")
    assert result["code"] == "TEST_LAYOUT_CONFLICT"
    assert "測試" in result["user_message"]
    assert result["auto_repairable"] is True


def test_run_center_hides_technical_details_until_diagnostics() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    diagnostics = (root / "static" / "js" / "features" / "diagnostics.js").read_text(encoding="utf-8")
    assert all(panel in html for panel in ("overviewPanel", "validationPanel"))
    assert "changesPanel" not in html
    assert 'id="productFlow"' in html
    assert all(stage in html for stage in ("requirement", "progress", "changes", "validation", "complete"))
    assert "renderProductFlow" in js
    assert "技術診斷" in html
    assert "執行時間線" in html and "執行產物" in html and "修復策略" in html
    assert 'id="diagnosticPatch"' not in html
    assert "data-artifact-id" not in js[js.index("async openStepDetailModal"):js.index("ensureStepDetailModal")]
    assert "/debug-bundle" in diagnostics and "/export" not in diagnostics
    assert "AIWF_ARTIFACT_MODE" in (root / "app" / "workflow_runtime" / "run_artifacts.py").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "workflow-runner.css").read_text(encoding="utf-8")
    responsive = (root / "static" / "css" / "responsive.css").read_text(encoding="utf-8")
    assert "body.novice-mode #openDiagnostics" in css
    assert "body.novice-mode #runTimelineCard" in css
    assert "max-height: min(48vh, 405px)" in responsive


def test_v8_routes_expose_setup_analytics_actions_and_compaction() -> None:
    paths = set(app.openapi()["paths"])
    assert "/api/setup/status" in paths
    assert "/api/setup/smoke" in paths
    assert "/api/analytics/summary" in paths
    assert "/api/optimization/recommend" in paths
    assert "/api/workflow-runs/{run_id}/actions" in paths
    assert "/api/workflow-runs/{run_id}/overview" in paths
    assert "/api/workflow-runs/{run_id}/diagnostics" in paths
    assert "/api/workflow-runs/{run_id}/artifacts/compact" in paths
    assert "/api/maintenance/store/backup" in paths
    assert "/api/maintenance/store/status" in paths


def test_interrupted_run_clears_persisted_project_lock() -> None:
    run = {
        "id": "locked-run",
        "status": "running",
        "project_lock": {"run_id": "locked-run", "project_path": "C:/project"},
        "steps": [{"key": "build", "status": "running"}],
    }
    mark_stale_active_run_interrupted(run, reason="controller restart")
    assert run["status"] == "failed"
    assert run["restart_recoverable"] is True
    assert run["project_lock"] is None
    assert run["steps"][0]["error_code"] == "INTERRUPTED"


def test_setup_status_exposes_seven_readiness_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    status = asyncio.run(setup_status(str(tmp_path)))
    assert status["schema"] == "aiwf.setup-status.v2"
    assert status["ready"] is True
    assert len(status["steps"]) == 7
    assert {step["id"] for step in status["steps"]} == {
        "storage",
        "project_write",
        "agent_cli",
        "model_connection",
        "context_window",
        "session_resume",
        "tool_calling",
    }


def test_execution_optimizer_recommends_small_stable_flow_for_tiny_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    result = asyncio.run(recommend_execution("用 Python 建立一個泡沫排序函式", project_path=str(tmp_path)))
    assert result["ready"] is True
    recommendation = result["recommendation"]
    assert recommendation["workflow_id"] == "general-auto-development"
    assert recommendation["run_profile"] == "small"
    assert recommendation["thinking_level"] == "medium"
    assert result["estimate"]["task_range"][1] <= 2
    assert result["environment_ready"] is True


def test_optimizer_frontend_is_optional_and_user_applied() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "features" / "optimization.js").read_text(encoding="utf-8")
    assert 'id="planningRecommendation"' in html
    assert "applyExecutionRecommendation" in js
    assert "套用建議" in js
    assert "ctx.features.workflows.select" in js
    assert "setTimeout(() => optimization.load(text), 650)" in js


def test_recovery_counters_separate_attempts_restarts_replans_and_streaks() -> None:
    run: dict[str, Any] = {}
    increment_recovery_counter(run, "agent_attempts")
    increment_recovery_counter(run, "session_restarts")
    increment_recovery_counter(run, "replans")
    increment_recovery_counter(run, "consecutive_failures", 2)
    counters = public_recovery_counters(run)
    assert counters["agent_attempts"] == 1
    assert counters["session_restarts"] == 1
    assert counters["replans"] == 1
    assert counters["consecutive_failures"] == 2
    reset_consecutive_failures(run)
    assert public_recovery_counters(run)["consecutive_failures"] == 0


def test_setup_smoke_uses_isolated_mock_probe_and_project_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    result = asyncio.run(setup_smoke_test(str(tmp_path), agent_name="qwen", run_agent=True))
    assert result["ready"] is True
    assert result["isolated_agent_probe"] is True
    statuses = {step["id"]: step["status"] for step in result["steps"]}
    assert statuses == {
        "project_write": "passed",
        "agent_cli": "passed",
        "model_response": "passed",
        "session_create": "passed",
        "tool_write": "passed",
    }
    assert not list((tmp_path / ".ai-workflow").glob("setup-controller-probe-*.tmp"))


def test_setup_ui_offers_explicit_isolated_smoke_test() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "js" / "features" / "setup.js").read_text(encoding="utf-8")
    assert "/api/setup/smoke" in js
    assert "執行 Smoke Test" in js
    assert "暫存 Project" in js
