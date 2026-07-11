from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import project_content_snapshot
from app.workflow_runtime.base_actions import BaseAgentActionsMixin
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext
from app.workflow_runtime.builtin_functions.core import run_pytest
from app.workflow_runtime.executor import WorkflowExecutor
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.test_layout import repair_run_owned_test_layout


class _OwnershipActions(BaseAgentActionsMixin):
    pass


def _write_baseline(workspace: Path, files: dict[str, str]) -> None:
    target = workspace / ".workflow" / "project-snapshot-before.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"schema": "aiwf.project-text-snapshot.v1", "files": files}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_run_owned_root_test_is_removed_when_canonical_counterpart_exists(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    (project / "tests").mkdir(parents=True)
    (project / "test_bubble_sort.py").write_text("# accidental root test\n", encoding="utf-8")
    (project / "tests" / "test_bubble_sort.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _write_baseline(workspace, {})

    result = repair_run_owned_test_layout(project, workspace)

    assert result["status"] == "REPAIRED"
    assert result["removed_files"] == ["test_bubble_sort.py"]
    assert not (project / "test_bubble_sort.py").exists()
    assert (project / "tests" / "test_bubble_sort.py").is_file()


def test_preexisting_root_test_is_never_deleted(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    (project / "tests").mkdir(parents=True)
    root = project / "test_existing.py"
    root.write_text("def test_old():\n    assert True\n", encoding="utf-8")
    (project / "tests" / "test_existing.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")
    _write_baseline(workspace, {"test_existing.py": root.read_text(encoding="utf-8")})

    result = repair_run_owned_test_layout(project, workspace)

    assert root.is_file()
    assert result["removed_files"] == []
    assert result["preserved_files"] == [{"path": "test_existing.py", "reason": "file existed before this run"}]


def test_build_ownership_restores_tests_but_keeps_production(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    before = project_content_snapshot(project)
    (project / "bubble_sort.py").write_text("def bubble_sort(v):\n    return sorted(v)\n", encoding="utf-8")
    (project / "test_bubble_sort.py").write_text("def test_bad_location():\n    assert True\n", encoding="utf-8")
    files = [
        ("bubble_sort.py", (project / "bubble_sort.py").read_text(encoding="utf-8")),
        ("test_bubble_sort.py", (project / "test_bubble_sort.py").read_text(encoding="utf-8")),
    ]

    accepted, restored = _OwnershipActions()._enforce_phase_file_ownership(
        project, before, files, phase="build"
    )

    assert [path for path, _ in accepted] == ["bubble_sort.py"]
    assert restored == ["test_bubble_sort.py"]
    assert (project / "bubble_sort.py").is_file()
    assert not (project / "test_bubble_sort.py").exists()


def test_generate_tests_ownership_restores_production_change(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    source = project / "bubble_sort.py"
    source.write_text("def bubble_sort(v):\n    return sorted(v)\n", encoding="utf-8")
    before = project_content_snapshot(project)
    source.write_text("def bubble_sort(v):\n    return []\n", encoding="utf-8")
    test_file = project / "tests" / "test_bubble_sort.py"
    test_file.write_text("from bubble_sort import bubble_sort\n\ndef test_sort():\n    assert bubble_sort([2, 1]) == [1, 2]\n", encoding="utf-8")
    files = [
        ("bubble_sort.py", source.read_text(encoding="utf-8")),
        ("tests/test_bubble_sort.py", test_file.read_text(encoding="utf-8")),
    ]

    accepted, restored = _OwnershipActions()._enforce_phase_file_ownership(
        project, before, files, phase="generate_tests"
    )

    assert [path for path, _ in accepted] == ["tests/test_bubble_sort.py"]
    assert restored == ["bubble_sort.py"]
    assert "return sorted(v)" in source.read_text(encoding="utf-8")


def test_pytest_preflight_repairs_real_import_mismatch_without_ai_retry(tmp_path: Path) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        output = workspace / "output"
        (project / "tests").mkdir(parents=True)
        output.mkdir(parents=True)
        (project / "bubble_sort.py").write_text("def bubble_sort(v):\n    return sorted(v)\n", encoding="utf-8")
        (project / "test_bubble_sort.py").write_text("# duplicate root module\n", encoding="utf-8")
        (project / "tests" / "test_bubble_sort.py").write_text(
            "from bubble_sort import bubble_sort\n\ndef test_sort():\n    assert bubble_sort([2, 1]) == [1, 2]\n",
            encoding="utf-8",
        )
        _write_baseline(workspace, {})
        logs: list[str] = []

        async def log(_run: dict[str, Any], message: str) -> None:
            logs.append(message)

        async def refresh(_run_id: str) -> None:
            return None

        ctx = WorkflowFunctionContext(
            run={"id": "run-1", "workspace": str(workspace)},
            output_dir=output,
            project_dir=project,
            root_dir=tmp_path,
            read_text=lambda path: path.read_text(encoding="utf-8") if path.exists() else "",
            write_text=lambda path, value: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text(value, encoding="utf-8"))[1],
            log=log,
            refresh_artifacts=refresh,
        )
        await run_pytest(ctx)
        assert not (project / "test_bubble_sort.py").exists()
        assert "ExitCode: 0" in (output / "test-result.md").read_text(encoding="utf-8")
        report = json.loads((output / "test-layout-repair.json").read_text(encoding="utf-8"))
        assert report["removed_files"] == ["test_bubble_sort.py"]
        assert any("deterministic test-layout cleanup" in item for item in logs)

    asyncio.run(scenario())


def test_import_mismatch_has_dedicated_failure_class() -> None:
    failure = classify_failure("TEST_LAYOUT_CONFLICT: import file mismatch")
    assert failure["code"] == "TEST_LAYOUT_CONFLICT"
    assert failure["retry_target"] == "deterministic test-layout repair"


def test_retry_budget_belongs_to_failed_review_not_exhausted_repair_target(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        (workspace / "output").mkdir(parents=True)
        project.mkdir()
        run = {
            "id": "run-1",
            "workspace": str(workspace),
            "project_path": str(project),
            "status": "queued",
            "steps": [
                {"key": "auto_generation", "type": "ai", "status": "pending", "retry_count": 6, "max_retries": 3},
                {
                    "key": "ai_review",
                    "type": "review",
                    "status": "pending",
                    "retry_count": 0,
                    "max_retries": 2,
                    "config": {"retryPolicy": {"defaultRetryTo": "auto_generation", "maxRetries": 2}},
                },
            ],
        }
        counters = {"auto_generation": 0, "ai_review": 0}

        class Store:
            async def read(self):
                return {"runs": [run]}

        class Actions:
            def action_for_step(self, action_run, step, _output):
                key = step["key"]

                async def action():
                    counters[key] += 1
                    if key == "ai_review" and counters[key] == 1:
                        raise WorkflowError("review failed: missing evidence")

                return action

        async def update_run(_run_id, fn):
            fn(run)
            return run

        async def set_step(_run_id, key, status, error=None, error_code=None):
            step = next(item for item in run["steps"] if item["key"] == key)
            step.update({"status": status, "error": error, "error_code": error_code})

        async def reset_steps(_run_id, start):
            for item in run["steps"][start:]:
                item["status"] = "pending"
            return run

        async def get_retry(_run_id, key):
            return next(item for item in run["steps"] if item["key"] == key)["retry_count"]

        async def increment_retry(_run_id, key):
            step = next(item for item in run["steps"] if item["key"] == key)
            step["retry_count"] += 1
            return step["retry_count"]

        async def noop(*_args, **_kwargs):
            return None

        class Bus:
            async def publish(self, *_args, **_kwargs):
                return None

        executor = WorkflowExecutor(
            store=Store(),
            bus=Bus(),
            actions=Actions(),
            update_run=update_run,
            set_step=set_step,
            reset_steps_from=reset_steps,
            get_step_retry_count=get_retry,
            increment_step_retry=increment_retry,
            append_failure_feedback=noop,
            refresh_artifacts=noop,
            log=noop,
        )
        await executor.execute("run-1")

        assert run["status"] == "done"
        assert counters == {"auto_generation": 2, "ai_review": 2}
        assert run["steps"][0]["retry_count"] == 6
        assert run["steps"][1]["retry_count"] == 1
        assert run["retry_streaks"]["ai_review"] == 0

    asyncio.run(scenario())
