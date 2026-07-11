from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import validate_generated_test_files
from app.services import workflow_config_service
from app.workflow_runtime.completion_gate import evaluate_completion
from app.workflow_runtime.retry_policy import retry_target_for_failure
from app.workflow_runtime.run_diff import build_run_diff, write_baseline_snapshot
from app.workflow_runtime.task_loop_actions import TaskLoopActionsMixin
from app.workflow_runtime.validation_contract import ValidationContractError, build_validation_contract, verify_validation_contract


def test_parametrize_arguments_are_not_treated_as_fixtures(tmp_path: Path) -> None:
    files = [("tests/test_sort.py", """
import pytest
@pytest.mark.parametrize("func, case", [(lambda x: x, [1])])
def test_sort(func, case):
    assert func(case) == case
""")]
    validate_generated_test_files(files, project_dir=tmp_path)


def test_builtin_and_conftest_fixtures_are_supported(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("import pytest\n@pytest.fixture\ndef sample(): return 3\n", encoding="utf-8")
    files = [("tests/test_x.py", "def test_x(sample, tmp_path):\n    assert sample == 3\n")]
    validate_generated_test_files(files, project_dir=tmp_path)


def test_truly_missing_fixture_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(WorkflowError, match="unresolved required fixture"):
        validate_generated_test_files([("tests/test_x.py", "def test_x(missing_fixture):\n    assert True\n")], project_dir=tmp_path)


def test_test_definition_invalid_routes_to_generate_tests(tmp_path: Path) -> None:
    steps = [{"key": "build"}, {"key": "generate_tests"}, {"key": "run_test"}]
    target = retry_target_for_failure(
        {}, steps[2], steps, 2, tmp_path,
        error=WorkflowError("TEST_DEFINITION_INVALID: unresolved required fixture arguments"),
    )
    assert target == "generate_tests"


def test_deterministic_feedback_does_not_append_task_999() -> None:
    feedback = "## Retry Feedback for auto_generation\n\n### Error message to fix\n\nTEST_DEFINITION_INVALID: bad pytest collection"
    assert TaskLoopActionsMixin._feedback_is_generic_for_task_loop(feedback) is False


def test_run_diff_has_exact_per_file_counts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_dir = project / ".ai-workflow" / "runs" / "r1"
    project.mkdir(parents=True)
    run_dir.mkdir(parents=True)
    target = project / "a.py"
    target.write_text("a\nb\nc\n", encoding="utf-8")
    run = {"id": "r1", "project_path": str(project)}
    write_baseline_snapshot(run, run_dir)
    target.write_text("a\nB\nc\nd\n", encoding="utf-8")
    diff = build_run_diff(run, run_dir)
    assert diff["schema"] == "aiwf.run-diff.v2"
    assert diff["summary"] == {"files": 1, "added": 2, "removed": 1}
    assert diff["files"][0]["added"] == 2
    assert diff["files"][0]["removed"] == 1
    assert "+++ b/a.py" in diff["files"][0]["patch"]


def test_validation_contract_is_immutable(tmp_path: Path) -> None:
    script = tmp_path / "validation.py"
    script.write_text("raise SystemExit(0)\n", encoding="utf-8")
    contract = build_validation_contract(tmp_path, "validation.py", required=True)
    run = {"validation_contract": contract}
    verify_validation_contract(run)
    script.write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(ValidationContractError, match="VALIDATION_FILE_MUTATED"):
        verify_validation_contract(run)


def test_completion_gate_requires_executed_test_evidence(tmp_path: Path) -> None:
    run = {"workflow_id": "general-auto-development", "workspace": str(tmp_path), "steps": [], "tasks": []}
    result = evaluate_completion(run, output_dir=tmp_path)
    assert result["status"] == "FAIL"
    assert result["checks"]["automated_tests"]["status"] == "FAIL"


def test_completion_gate_requires_required_user_validation(tmp_path: Path) -> None:
    run = {
        "workflow_id": "adaptive-auto-workflow", "workspace": str(tmp_path), "steps": [], "tasks": [],
        "validation_contract": {"required": True},
        "validation_results": [{"key": "test", "status": "passed", "exit_code": 0}],
    }
    result = evaluate_completion(run, output_dir=tmp_path)
    assert result["status"] == "FAIL"
    run["validation_results"].append({"key": "user_validation", "status": "passed", "exit_code": 0})
    assert evaluate_completion(run, output_dir=tmp_path)["status"] == "PASS"


def test_product_catalog_exposes_exactly_three_workflows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(workflow_id: str, project_path=None):
        return {"id": workflow_id, "name": workflow_id, "kind": "system", "steps": [], "folderName": workflow_id}
    monkeypatch.setattr(workflow_config_service.workflow_asset_service, "load_workflow_asset", fake_load)
    # service calls this synchronously; use a sync substitute
    monkeypatch.setattr(workflow_config_service.workflow_asset_service, "load_workflow_asset", lambda workflow_id, project_path=None: {"id": workflow_id, "name": workflow_id, "kind": "system", "steps": [], "folderName": workflow_id})
    monkeypatch.setattr(workflow_config_service.workflow_asset_service, "function_catalog", lambda project_path=None: [])
    payload = asyncio.run(workflow_config_service.list_workflows())
    ids = [payload["system"]["id"], *[item["id"] for item in payload["systems"]], *[item["id"] for item in payload["custom"]]]
    assert ids == ["general-auto-development", "adaptive-auto-workflow", "security-scan"]


def test_ui_contract_is_dismissible_and_single_layer() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    assert 'id="dismissSetupStatus"' in html
    assert ".setup-status-card.compact-notice[hidden]" in css
    assert 'class="change-review-stage change-review-empty"' in html
    assert 'class="change-preview change-review-empty"' not in html
    assert "hunk[4]" not in runs
    assert 'class="patch-review-host"' in html
