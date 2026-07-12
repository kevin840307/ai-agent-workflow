from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.workflow_runtime.agent_step_runner import AgentStepRunner
from app.workflow_runtime.agent_stream_events import AgentJsonStreamParser
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.core import adaptive_python_gate
from app.workflow_runtime.complexity import classify_workflow_complexity
from app.workflow_runtime.project_hygiene import inspect_project_hygiene
from app.workflow_runtime.retry_guard import clear_retry_history, record_failure_attempt
from app.workflow_runtime.retry_policy import retry_target_for_failure


def test_tool_results_are_status_only_and_never_final_output() -> None:
    parser = AgentJsonStreamParser()
    first = parser.feed_line('{"type":"tool_result","result":"Successfully overwrote file: sort.py"}')
    second = parser.feed_line('{"type":"tool_result","result":"Successfully overwrote file: sort.py"}')
    final = parser.feed_line('{"type":"result","role":"assistant","result":"Implementation completed."}')

    assert first == [("status", "Successfully overwrote file: sort.py")]
    assert second == []
    assert final == [("display", "Implementation completed.")]
    assert parser.final_text() == "Implementation completed."


def test_auto_apply_executes_in_exact_selected_project() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        selected = root / "sort2"
        selected.mkdir()
        run_workspace = selected / ".ai-workflow" / "runs" / "run-1"
        run_workspace.mkdir(parents=True)
        run = {
            "patch_mode": "auto_apply",
            "project_path": str(run_workspace / ".workflow" / "isolated-workspace" / "agent-project"),
            "original_project_path": str(selected),
            "workspace": str(run_workspace),
        }
        assert AgentStepRunner._execution_project_dir(run) == selected.resolve()


def test_retry_guard_tracks_source_separately_from_retry_target_and_clears() -> None:
    run: dict[str, object] = {}
    attempt = record_failure_attempt(
        run,
        step_key="build",
        task_id="TASK-001",
        retry_target="plan_tasks",
        error="NO_FILE_CHANGE: agent did not modify files",
    )
    assert attempt["source_step"] == "build"
    assert attempt["retry_target"] == "plan_tasks"
    assert run["retry_guard_history"][0]["source_step"] == "build"  # type: ignore[index]
    assert clear_retry_history(run, step_key="build", task_id="TASK-001") == 1
    assert run["retry_guard_history"] == []


def test_review_format_and_mutation_failures_retry_review_not_build_or_planner(tmp_path: Path) -> None:
    steps = [
        {"key": "build", "type": "agent"},
        {
            "key": "implementation_review",
            "type": "review",
            "config": {"retryPolicy": {"defaultRetryTo": "build"}},
        },
    ]
    review = steps[1]
    assert retry_target_for_failure(
        {}, review, steps, 1, tmp_path,
        error="INVALID_REVIEW_OUTPUT: expected JSON",
    ) == "implementation_review"
    assert retry_target_for_failure(
        {}, review, steps, 1, tmp_path,
        error="REVIEW_MUTATED_PROJECT: changes reverted",
    ) == "implementation_review"


def test_tiny_complexity_caps_plan_at_two_tasks() -> None:
    with TemporaryDirectory() as tmp:
        result = classify_workflow_complexity("用 Python 建立泡沫排序", Path(tmp))
    assert result["profile"] == "tiny"
    assert result["max_tasks"] == 2
    assert result["recommended_tasks"] == "1-2"
    assert result["source"] == "project_metrics"


def test_project_hygiene_rejects_duplicate_implementations_and_embedded_test_code() -> None:
    with TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "tests").mkdir()
        body = "def bubble_sort(values):\n    result = list(values)\n    result.sort()\n    return result\n"
        (project / "bubble_sort.py").write_text(body, encoding="utf-8")
        (project / "sort.py").write_text(body, encoding="utf-8")
        (project / "tests" / "test_sort.py").write_text(
            body + "\ndef test_sort():\n    assert bubble_sort([2, 1]) == [1, 2]\n",
            encoding="utf-8",
        )
        result = inspect_project_hygiene(project)
    assert result["status"] == "FAIL"
    assert any("Duplicate public implementations" in item for item in result["errors"])
    assert any("redefine production functions" in item for item in result["errors"])


def test_adaptive_python_gate_executes_run_tests_py() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            output = root / "workspace" / "output"
            project.mkdir(parents=True)
            output.mkdir(parents=True)
            (project / "sort.py").write_text(
                "def bubble_sort(values):\n    return sorted(values)\n",
                encoding="utf-8",
            )
            (project / "run_tests.py").write_text(
                "from sort import bubble_sort\nassert bubble_sort([2, 1]) == [1, 2]\nprint('all passed')\n",
                encoding="utf-8",
            )
            logs: list[str] = []

            async def log(_run: dict, message: str) -> None:
                logs.append(message)

            async def refresh(_run_id: str) -> None:
                return None

            ctx = WorkflowFunctionContext(
                run={"id": "run-1", "workspace": str(output.parent)},
                output_dir=output,
                project_dir=project,
                root_dir=root,
                read_text=lambda path: path.read_text(encoding="utf-8") if path.exists() else "",
                write_text=lambda path, text: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text(text, encoding="utf-8"))[1],
                log=log,
                refresh_artifacts=refresh,
            )
            await adaptive_python_gate(ctx)
            report = (output / "python-gate-result.md").read_text(encoding="utf-8")
            assert "Status: PASS" in report
            assert "Mode: run_tests.py" in report
            assert "all passed" in report
            hygiene = json.loads((output / "project-hygiene.json").read_text(encoding="utf-8"))
            assert hygiene["status"] == "PASS"

    asyncio.run(scenario())


def test_python_source_without_tests_fails_instead_of_fake_pass() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            output = root / "workspace" / "output"
            project.mkdir(parents=True)
            output.mkdir(parents=True)
            (project / "sort.py").write_text("def sort(values):\n    return sorted(values)\n", encoding="utf-8")

            async def noop(*_args, **_kwargs) -> None:
                return None

            ctx = WorkflowFunctionContext(
                run={"id": "run-1", "workspace": str(output.parent)},
                output_dir=output,
                project_dir=project,
                root_dir=root,
                read_text=lambda path: path.read_text(encoding="utf-8") if path.exists() else "",
                write_text=lambda path, text: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text(text, encoding="utf-8"))[1],
                log=noop,
                refresh_artifacts=noop,
            )
            with pytest.raises(WorkflowFunctionError, match="VALIDATION_NOT_EXECUTED"):
                await adaptive_python_gate(ctx)
            assert "Status: FAIL" in (output / "python-gate-result.md").read_text(encoding="utf-8")

    asyncio.run(scenario())
