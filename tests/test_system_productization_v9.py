from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workflow.agents.errors import classify_agent_error
from app.workflow.agents.providers.generic_cli import GenericCliAdapter
from app.workflow.agents.providers.opencode import OpenCodeCliAdapter
from app.workflow.agents.providers.qwen import QwenAdapter
from app.workflow_runtime.benchmark_catalog import benchmark_catalog, benchmark_summary
from app.workflow_runtime.context_handoff import build_context_handoff, write_context_handoff
from app.workflow_runtime.model_capabilities import prompt_limits_for, resolve_model_capability
from app.workflow_runtime.release_manager import upgrade_readiness, version_manifest, write_version_manifest
from app.workflow_runtime.risk_engine import assess_risk, should_pause_for_approval
from app.workflow_runtime.scope_control import analyze_scope_delta
from app.workflow_runtime.task_checkpoints import create_task_checkpoint, restore_task_checkpoint
from app.workflow_runtime.validators import detect_validator_plans, execute_validator_plan, primary_validator


def test_model_capability_profiles_change_prompt_and_task_limits() -> None:
    small = resolve_model_capability("small")
    strong = resolve_model_capability("strong")
    assert small["context_window"] < strong["context_window"]
    assert small["max_files_per_task"] < strong["max_files_per_task"]
    limits = prompt_limits_for("normal", context_window=100_000)
    assert limits == {
        "context_window": 100_000,
        "warn_tokens": 60_000,
        "handoff_tokens": 75_000,
        "hard_tokens": 90_000,
        "prompt_budget_chars": 35_000,
    }


def test_risk_engine_selects_review_and_dry_run_for_sensitive_work() -> None:
    high = assess_risk("Modify authentication and database migration code")
    assert high["level"] in {"high", "critical"}
    assert high["recommended"]["patch_mode"] in {"review", "dry_run"}
    assert high["approval_required"] is True
    assert should_pause_for_approval(high, "review_before_apply", "before_apply") is True
    critical = assess_risk("Drop table from production database and rotate private key")
    assert critical["level"] == "critical"
    assert critical["recommended"]["approval_mode"] == "plan_and_patch_only"


def test_scope_delta_reports_unrequested_docs_and_examples() -> None:
    result = analyze_scope_delta(
        "Create a bubble_sort function",
        file_changes=[{"path": "bubble_sort.py"}, {"path": "README.md"}, {"path": "example.py"}],
        planned_tasks=[{"id": "TASK-001"}],
    )
    assert result["status"] == "warning"
    assert result["unrequested_count"] == 2
    assert {item["kind"] for item in result["expansions"]} >= {"unrequested_documentation", "unrequested_example"}


def test_context_handoff_is_structured_bounded_and_written(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "run"
    project.mkdir()
    (project / "source.py").write_text("print('ok')\n", encoding="utf-8")
    (workspace / "input").mkdir(parents=True)
    (workspace / "requirement.md").write_text("Build a small feature", encoding="utf-8")
    run = {
        "id": "run-1",
        "workflow_id": "general-auto-development",
        "workspace": str(workspace),
        "steps": [{"key": "build", "status": "failed", "retry_count": 1}],
        "tasks": [{"id": "TASK-001", "title": "Build", "status": "passed"}],
        "validation_results": [{"key": "pytest", "status": "failed", "summary": "one failure"}],
    }
    payload, markdown = write_context_handoff(run, step_key="build", project_dir=project, workspace_path=workspace, error="context too large")
    assert payload["schema"] == "aiwf.context-handoff.v2"
    assert payload["completed_tasks"][0]["id"] == "TASK-001"
    assert "Re-read files from disk" in markdown
    assert (workspace / "input" / "session-handoff.json").is_file()
    assert run["context_handoffs"][-1]["step_key"] == "build"


def test_task_checkpoint_restores_last_accepted_project_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "run"
    project.mkdir()
    workspace.mkdir()
    (project / "a.txt").write_text("accepted", encoding="utf-8")
    run = {"id": "run", "workspace": str(workspace), "project_path": str(project)}
    record = create_task_checkpoint(run, task_id="TASK-001", step_key="build", project_dir=project, changed_files=["a.txt"])
    assert record["complete"] is True
    (project / "a.txt").write_text("broken", encoding="utf-8")
    (project / "extra.txt").write_text("remove me", encoding="utf-8")
    restored = restore_task_checkpoint(run, record["id"], project_dir=project)
    assert restored["restored"] is True
    assert (project / "a.txt").read_text(encoding="utf-8") == "accepted"
    assert not (project / "extra.txt").exists()


def test_task_checkpoint_retention_prunes_old_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIWF_TASK_CHECKPOINT_KEEP", "2")
    project = tmp_path / "project"
    workspace = tmp_path / "run"
    project.mkdir(); workspace.mkdir()
    run = {"id": "run", "workspace": str(workspace), "project_path": str(project)}
    ids = []
    for index in range(4):
        (project / "value.txt").write_text(str(index), encoding="utf-8")
        ids.append(create_task_checkpoint(run, task_id=f"TASK-{index:03d}", step_key="build", project_dir=project)["id"])
    assert len(run["task_checkpoints"]) == 2
    checkpoint_dir = workspace / ".workflow" / "checkpoints"
    assert not (checkpoint_dir / f"{ids[0]}.zip").exists()
    assert (checkpoint_dir / f"{ids[-1]}.zip").exists()


def test_validator_plugins_detect_python_xml_sql_and_custom(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "config.xml").write_text("<root />", encoding="utf-8")
    (tmp_path / "query.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / ".ai-workflow-validator.json").write_text(json.dumps({"id": "project-check", "command": ["python", "-c", "print('ok')"]}), encoding="utf-8")
    plans = detect_validator_plans(tmp_path)
    ids = {item["id"] for item in plans}
    assert {"project-check", "python", "xml", "sql"} <= ids
    assert primary_validator(tmp_path)["id"] == "project-check"


def test_xml_validator_executes_without_external_tool(tmp_path: Path) -> None:
    (tmp_path / "config.xml").write_text("<root><child /></root>", encoding="utf-8")
    result = asyncio.run(execute_validator_plan(tmp_path, validator_id="xml", timeout_sec=10))
    assert result["status"] == "passed"
    assert result["exit_code"] == 0


def test_agent_adapter_capabilities_and_error_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    adapters = [QwenAdapter(), OpenCodeCliAdapter({"mock": True}), GenericCliAdapter({"mock": True})]
    assert all(adapter.capabilities().streaming for adapter in adapters)
    assert QwenAdapter.classify_error("No saved session found with ID abc")["code"] == "SESSION_NOT_FOUND"
    assert classify_agent_error("Context is too large after compression status: NOOP")["strategy"] == "handoff_fresh_session"
    assert classify_agent_error("401 Incorrect API key")["recoverable"] is False


def test_release_manifest_and_upgrade_readiness(tmp_path: Path) -> None:
    manifest = version_manifest()
    assert manifest["app_version"] == "1.0.0"
    assert manifest["database_schema"] == 9
    path = write_version_manifest(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["workflow_schema"] == 6
    readiness = upgrade_readiness(tmp_path / "store.sqlite3")
    assert readiness["backup_supported"] is True
    assert len(readiness["steps"]) >= 5


def test_benchmark_catalog_and_summary_track_real_run_outcomes() -> None:
    catalog = benchmark_catalog()
    assert catalog["count"] == 10
    summary = benchmark_summary([
        {"benchmark_id": "BENCH-001", "status": "done", "steps": [{"retry_count": 0}]},
        {"benchmark_id": "BENCH-001", "status": "failed", "steps": [{"retry_count": 2}]},
    ])
    bench = next(item for item in summary["cases"] if item["id"] == "BENCH-001")
    assert bench["runs"] == 2
    assert bench["success_rate"] == 50.0
    assert bench["average_retry"] == 1.0


def test_setup_status_exposes_mock_mode_without_showing_optional_context_as_blocking(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    monkeypatch.delenv("AIWF_CONTEXT_WINDOW", raising=False)
    from app.services.setup_service import setup_status

    result = asyncio.run(setup_status(str(tmp_path)))
    assert result["mock_mode"] is True
    assert result["ready"] is True
    context = next(item for item in result["steps"] if item["id"] == "context_window")
    assert context["required"] is False



def test_high_risk_run_defaults_to_isolated_patch_and_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    project = tmp_path / "project"
    project.mkdir()
    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": "risk-review", "project_path": str(project)})
        assert session.status_code == 200, session.text
        run = client.post(
            f"/api/sessions/{session.json()['id']}/workflow-runs",
            json={
                "workflow_id": "general-auto-development",
                "requirement": "Modify authentication and database migration code safely.",
                "runProfile": "normal",
            },
        )
        assert run.status_code == 200, run.text
        payload = run.json()
        assert payload["patch_mode"] == "review"
        assert payload["approval_mode"] == "review_before_apply"
        assert payload["approval_state"] == "pending"
        assert payload["isolated_project_path"]
        client.post(f"/api/workflow-runs/{payload['id']}/terminate")

def test_v9_productization_routes_are_exposed() -> None:
    paths = {route.path for route in app.routes}
    assert {
        "/api/productization/version",
        "/api/productization/upgrade-readiness",
        "/api/productization/model-profiles",
        "/api/productization/validators",
        "/api/productization/validators/run",
        "/api/benchmarks/catalog",
        "/api/benchmarks/summary",
    } <= paths


def test_v9_route_payloads_work_with_test_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWEN_MOCK", "1")
    (tmp_path / "config.xml").write_text("<root />", encoding="utf-8")
    with TestClient(app) as client:
        version = client.get("/api/productization/version")
        assert version.status_code == 200 and version.json()["version"]["app_version"] == "1.0.0"
        validators = client.get("/api/productization/validators", params={"project_path": str(tmp_path)})
        assert validators.status_code == 200
        result = client.post("/api/productization/validators/run", json={"project_path": str(tmp_path), "validator_id": "xml", "timeout_sec": 10})
        assert result.status_code == 200 and result.json()["status"] == "passed"


def test_ui_uses_dismissible_setup_notice_and_center_result_modal() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "workflow-runner.css").read_text(encoding="utf-8")
    setup = (root / "static" / "js" / "features" / "setup.js").read_text(encoding="utf-8")
    runs = (root / "static" / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    events = (root / "static" / "js" / "features" / "events.js").read_text(encoding="utf-8")
    assert 'id="dismissSetupStatus"' in html
    assert 'class="run-result-modal-backdrop"' in html
    assert 'class="run-result-panel result-dock"' not in html
    assert ".setup-status-card.compact-notice[hidden]" in css
    assert ".run-result-modal-backdrop" in css and "place-items: center" in css
    assert ".run-result-modal" in css and "max-height: min(82vh, 680px)" in css
    assert "setupNoticeDismissed" in setup
    assert "openResultModal" in runs and "closeResultModal" in runs
    assert 'event.target === ui.byKey("runResultPanel")' in events
    assert 'event.key === "Escape"' in events


def test_ui_recommendation_is_compact_user_applied_and_closable() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "static" / "js" / "features" / "optimization.js").read_text(encoding="utf-8")
    events = (root / "static" / "js" / "features" / "events.js").read_text(encoding="utf-8")
    assert 'class="planning-recommendation recommendation-chip"' in html
    assert "<details class=\"recommendation-details\">" in js
    assert "套用" in js and "不再顯示" in js
    assert "appliedExecutionRecommendation" in js
    assert "recommendation.open = false" in events


def test_ui_changes_and_patch_are_file_first_with_split_and_unified_views() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    runs = (root / "static" / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    diagnostics = (root / "static" / "js" / "features" / "diagnostics.js").read_text(encoding="utf-8")
    assert "先選檔案、看差異，再決定套用。" in html
    assert "data-patch-view=\"split\"" in html and "data-patch-view=\"unified\"" in html
    assert "change-filter-group" in runs and "change-owner" in runs and "scope-warning" in runs
    assert "diff-code-row" in runs and "change-approval-bar" in runs
    assert "patch-file-option" in diagnostics and "selectedPatchFiles" in diagnostics
    assert "data-patch-search" in diagnostics and "data-patch-select" in diagnostics
    assert "核准此 Patch" in diagnostics and "applySelectedPatch" in diagnostics


def test_ui_run_center_has_collapsed_timeline_and_human_retry() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    runs = (root / "static" / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    assert 'id="runTimelineCard"' in html
    assert "renderTimeline(events)" in runs
    assert "human-retry" in runs
    assert "第 ${Number(retry.attempt)} 次修復" in runs


def test_v9_docs_and_benchmark_runner_are_included() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("CHANGELOG.md", "UPGRADE.md", "MIGRATIONS.md"):
        assert (root / name).is_file()
    runner = (root / "scripts" / "run_productization_benchmarks.py").read_text(encoding="utf-8")
    assert "BENCH-010" in runner and "--real" in runner and "--execute" in runner
