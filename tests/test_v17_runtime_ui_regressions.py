from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.runtime_modules.errors import WorkflowError
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionError
from app.workflow_runtime.candidate_validation import validate_agent_candidate
from app.workflow_runtime.functions import WorkflowFunctionService
from app.workflow_runtime.run_diff import write_baseline_snapshot
from app.workflow_runtime.task_loop_actions import TaskLoopActionsMixin


def test_cumulative_candidate_rejects_invalid_production_left_by_previous_attempt(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_dir = tmp_path / "run"
    project.mkdir()
    run_dir.mkdir()
    run = {"id": "run-1", "workspace": str(run_dir), "project_path": str(project)}
    write_baseline_snapshot(run, run_dir)

    # Attempt 1 left pytest code in a production file. Attempt 2 only created
    # a proper test file. The cumulative candidate must still be rejected.
    (project / "sort_algorithms.py").write_text(
        "def bubble_sort(values):\n    return sorted(values)\n\ndef test_sort_algorithms():\n    assert bubble_sort([2, 1]) == [1, 2]\n",
        encoding="utf-8",
    )
    tests = project / "tests"
    tests.mkdir()
    test_file = tests / "test_sort_algorithms.py"
    test_file.write_text(
        "from sort_algorithms import bubble_sort\n\ndef test_sort():\n    assert bubble_sort([2, 1]) == [1, 2]\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="test code must be separated"):
        validate_agent_candidate(
            run=run,
            project_dir=project,
            run_workspace=run_dir,
            direct_files=[("tests/test_sort_algorithms.py", test_file.read_text(encoding="utf-8"))],
            validation_script=None,
            fallback_scripts=[],
        )

    (project / "sort_algorithms.py").write_text(
        "def bubble_sort(values):\n    return sorted(values)\n",
        encoding="utf-8",
    )
    candidate = validate_agent_candidate(
        run=run,
        project_dir=project,
        run_workspace=run_dir,
        direct_files=[("sort_algorithms.py", (project / "sort_algorithms.py").read_text(encoding="utf-8"))],
        validation_script=None,
        fallback_scripts=[],
    )
    assert {path for path, _ in candidate} == {"sort_algorithms.py", "tests/test_sort_algorithms.py"}


def test_blank_review_feedback_does_not_create_synthetic_repair_task() -> None:
    feedback = """## Retry Feedback for auto_generation

- Failed step: ai_review

### Error message to fix
"""
    assert TaskLoopActionsMixin._feedback_is_generic_for_task_loop(feedback) is False


def test_python_function_failure_never_becomes_blank(monkeypatch, tmp_path: Path) -> None:
    async def log(_run, _message):
        return None

    async def refresh(_run_id):
        return None

    service = WorkflowFunctionService(log=log, refresh_artifacts=refresh)

    def blank_failure(_ctx):
        raise WorkflowFunctionError()

    monkeypatch.setitem(__import__("app.workflow_runtime.functions", fromlist=["PYTHON_FUNCTIONS"]).PYTHON_FUNCTIONS, "blank_failure", blank_failure)
    run = {"id": "r", "workspace": str(tmp_path), "project_path": str(tmp_path)}
    with pytest.raises(WorkflowError, match="blank_failure failed with WorkflowFunctionError"):
        asyncio.run(service.call_python_function(run, "blank_failure", tmp_path))


def test_v17_ui_removes_profile_badge_and_owns_scroll_surfaces() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "workflow-runner.css").read_text(encoding="utf-8")
    events = (root / "static" / "js" / "features" / "events.js").read_text(encoding="utf-8")

    assert 'id="projectValidationStatus"' not in index
    assert 'projectValidationStatus"' not in events
    project_profile = (root / "static" / "js" / "features" / "project-profile.js").read_text(encoding="utf-8")
    assert 'ui.byKey("projectValidationStatus")' not in project_profile
    assert 'class="diagnostics-title-line"' in index
    assert '#diagnosticArtifacts.active' in css
    assert 'grid-template-areas: "toolbar toolbar" "files content"' in css
    assert 'V17 single-scroll workspace contract' in css
    assert '.run-center > .panel.active' in css
    assert '.diagnostic-section.active' in css
    assert 'overflow-y: visible !important' in css
    assert '.run-center-collapsed-launch' in css
    assert '.diff-dialog-backdrop' in css
    assert 'grid-template-columns: clamp(250px, 24vw, 380px) minmax(0, 1fr)' in css


def test_runtime_repair_policy_is_extracted_and_keeps_mixin_compatibility() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = (root / "app" / "workflow_runtime" / "repair_task_policy.py").read_text(encoding="utf-8")
    loop = (root / "app" / "workflow_runtime" / "task_loop_actions.py").read_text(encoding="utf-8")
    assert "def is_generic_task_loop_feedback" in policy
    assert "def append_generic_repair_task" in policy
    assert "return is_generic_task_loop_feedback(feedback)" in loop
    assert "return append_generic_repair_task(tasks, owner=owner)" in loop


def test_test_layout_failure_does_not_create_task_999() -> None:
    feedback = """## Retry Feedback for auto_generation

- Failed step: ai_review

### Error message to fix
test code must be separated from production files. Put pytest tests under tests/.
"""
    assert TaskLoopActionsMixin._feedback_is_generic_for_task_loop(feedback) is False
