from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.agents.process_supervisor import ProcessSupervisorOptions, run_supervised_process
from app.core.provider_slots import provider_execution_slot, provider_limit
from app.runtime_modules.errors import WorkflowError
from app.security.redaction import redact_text, redact_value
from app.workflow_runtime.benchmark import compare_runs
from app.workflow_runtime.impacted_tests import identify_impacted_tests
from app.workflow_runtime.project_index_cache import get_cached_project_index
from app.workflow_runtime.retry_guard import clear_retry_history, should_stop_retry
from app.workflow_runtime.task_acceptance import normalize_task_contract, validate_task_file_changes
from app.workflow_runtime.validators.plan import build_validation_plan

ROOT = Path(__file__).resolve().parents[1]


def test_secret_redaction_covers_common_agent_and_validator_outputs() -> None:
    text = "Authorization: Bearer abc.def\nOPENAI_API_KEY=sk-secret123\npassword: super-secret\nhttps://user:pass@example.test/api"
    redacted = redact_text(text)
    assert "abc.def" not in redacted
    assert "sk-secret123" not in redacted
    assert "super-secret" not in redacted
    assert "user:pass" not in redacted
    nested = redact_value({"stdout": text, "items": [text]})
    assert "sk-secret123" not in str(nested)


def test_provider_slots_allow_concurrent_sessions_but_bound_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIWF_V15TEST_MAX_CONCURRENCY", "2")

    async def scenario() -> int:
        active = 0
        maximum = 0
        lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal active, maximum
            async with provider_execution_slot("v15test"):
                async with lock:
                    active += 1
                    maximum = max(maximum, active)
                await asyncio.sleep(0.05)
                async with lock:
                    active -= 1

        await asyncio.gather(*(worker() for _ in range(5)))
        return maximum

    assert provider_limit("v15test") == 2
    assert asyncio.run(scenario()) == 2


def test_retry_budget_survives_fresh_session_history_clear() -> None:
    run = {
        "created_at": "2026-07-11T00:00:00+00:00",
        "recoveryBudget": {
            "maxRunFailures": 4,
            "maxStepFailures": 20,
            "maxTaskFailures": 20,
            "maxFailureClass": 20,
            "maxFingerprint": 20,
            "wallClockMinutes": 0,
            "freshSessionEvery": 0,
        },
        "steps": [{"key": "build"}],
    }
    for index in range(3):
        stop, _, attempt = should_stop_retry(run, step_key="build", task_id="TASK-001", error=f"different failure {index}")
        assert stop is False
        clear_retry_history(run, step_key="build", task_id="TASK-001")
        assert attempt["run_failure_count"] == index + 1
    stop, reason, attempt = should_stop_retry(run, step_key="build", task_id="TASK-001", error="fourth failure")
    assert stop is True
    assert attempt["hard_stop"] is True
    assert "run failure budget" in str(reason)


def test_process_supervisor_detects_no_output_stall(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(WorkflowError, match="stalled with no output"):
            await run_supervised_process(
                ProcessSupervisorOptions(
                    command=[sys.executable, "-c", "import time; time.sleep(5)"],
                    cwd=tmp_path,
                    timeout_sec=10,
                    stall_timeout_sec=1,
                    heartbeat_interval_sec=0,
                )
            )

    asyncio.run(scenario())


def test_incremental_project_index_cache_is_controller_owned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    import app.workflow_runtime.project_index_cache as cache_module

    monkeypatch.setattr(cache_module, "_CACHE_DIR", cache_dir)
    first, first_info = get_cached_project_index(project)
    second, second_info = get_cached_project_index(project)
    assert first == second
    assert first_info["status"] == "miss"
    assert second_info["status"] == "hit"
    assert not (project / "project-index.md").exists()
    (project / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    _, third_info = get_cached_project_index(project)
    assert third_info["status"] == "miss"


def test_impacted_tests_accelerate_but_full_suite_remains_required(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "config_loader.py").write_text("def load(): return {}\n", encoding="utf-8")
    (tmp_path / "tests" / "test_config_loader.py").write_text("from src.config_loader import load\n\ndef test_load(): assert load() == {}\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    impact = identify_impacted_tests(tmp_path, [{"path": "src/config_loader.py"}])
    assert impact["tests"][0]["path"] == "tests/test_config_loader.py"
    assert impact["full_suite_required"] is True
    plan = build_validation_plan(tmp_path, changed_files=[{"path": "src/config_loader.py"}])
    ids = [phase["id"] for phase in plan["phases"]]
    assert ids.index("python-focused-test") < ids.index("python-test")


def test_task_acceptance_contract_only_enforces_ai_authored_paths() -> None:
    task = normalize_task_contract(
        {
            "id": "TASK-001",
            "scope": ["src/**", "tests/**"],
            "mustChange": ["src/config.py"],
            "mustNotChange": ["validation.py"],
            "acceptance": ["tests pass"],
        },
        owner="build",
    )
    assert validate_task_file_changes(task, ["src/config.py"]) == []
    violations = validate_task_file_changes(task, ["README.md", "validation.py"])
    assert any("outside task scope" in item for item in violations)
    assert any("protected task path" in item for item in violations)
    assert any("were not changed" in item for item in violations)


def test_run_comparison_reports_quality_delta() -> None:
    left = {
        "id": "old",
        "status": "failed",
        "steps": [{"retry_count": 4, "status": "waiting_input"}],
        "validation_results": [{"status": "failed"}],
        "file_changes": [{"path": "a.py"}, {"path": "b.py"}],
    }
    right = {
        "id": "new",
        "status": "done",
        "steps": [{"retry_count": 1, "status": "passed"}],
        "validation_results": [{"status": "passed"}],
        "file_changes": [{"path": "a.py"}],
    }
    result = compare_runs(left, right)
    assert result["delta"]["retry_count"] == -3
    assert result["improved"]["status"] is True
    assert result["improved"]["less_manual_intervention"] is True


def test_run_center_tabs_and_validation_have_independent_layout_boundaries() -> None:
    layout = (ROOT / "static/css/layout.css").read_text(encoding="utf-8")
    css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    events = (ROOT / "static/js/features/events.js").read_text(encoding="utf-8")
    assert "grid-template-rows: auto auto auto minmax(0, 1fr)" in layout
    v15 = css.split("/* V15 Run Center containment", 1)[1]
    assert ".run-center-tabs" in v15 and "min-height: 43px" in v15 and "max-height: 43px" in v15
    assert "#validationPanel.active" in v15 and "overflow: hidden" in v15
    assert "#validationPanel .validation-list" in v15 and "overflow: auto" in v15
    assert 'id="collapseRunCenter"' in html
    assert "setDetailsCollapsed(true)" in events


def test_controller_does_not_materialize_agent_file_blocks() -> None:
    base = (ROOT / "app/workflow_runtime/base_actions.py").read_text(encoding="utf-8")
    general = (ROOT / "app/workflow_runtime/general_actions.py").read_text(encoding="utf-8")
    adaptive = (ROOT / "app/workflow_runtime/adaptive_actions.py").read_text(encoding="utf-8")
    assert "_apply_file_blocks_for_direct_edit" not in base + general + adaptive
    assert "apply_extracted_files(project_dir" not in base
    assert "Use Qwen/OpenCode file edit/write tools" in general


def test_bilingual_docs_are_consolidated_and_keep_validation_example() -> None:
    expected = {"README.md", "QUICKSTART.md", "USER_GUIDE.md", "VALIDATION.md", "ARCHITECTURE.md", "OPERATIONS.md", "EXTENDING.md", "TESTING.md"}
    for language in ("en", "zh-TW"):
        files = {path.name for path in (ROOT / "doc" / language).glob("*.md")}
        assert files == expected
        validation = (ROOT / "doc" / language / "VALIDATION.md").read_text(encoding="utf-8")
        assert "def main() -> int:" in validation
        assert "--project" in validation
        assert "bubble_sort" in validation


def test_real_agent_certification_has_twelve_scenarios_and_release_metrics() -> None:
    from app.services.real_agent_matrix_service import build_real_agent_matrix, summarize_real_agent_rows

    matrix = build_real_agent_matrix(agents=["qwen"], workflows=["general-auto-development"], cases=["sort"])
    assert matrix["schema"] == "aiwf.real-agent-matrix.v4"
    assert matrix["certification"]["scenario_count"] == 12
    assert matrix["certification"]["quality_thresholds"]["success_after_repair_min"] == 0.90
    rows = [
        {
            "status": "passed",
            "duration_seconds": 10,
            "result": {
                "schema": "aiwf.real-agent-acceptance-cell.v1",
                "acceptance": {
                    "external_validation_passed": True,
                    "retry_total": 1,
                    "manual_intervention": False,
                    "scope_violation_count": 0,
                    "session_count": 2,
                },
            },
        }
    ]
    metrics = summarize_real_agent_rows(rows)
    assert metrics["success_after_repair"] == 1.0
    assert metrics["fresh_session_count"] == 1
    assert metrics["certified"] is True
