from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.command_runner import CommandResult
from app.main import app
from app.services import workflow_asset_service
from app.workflow_runtime.builtin_functions import core as builtin_core
from app.workflow_runtime.validators import plan as validation_plan
from app.workflow_runtime.validators import registry as validation_registry


def _command_result(*, returncode: int = 0, timed_out: bool = False) -> CommandResult:
    return CommandResult(
        command="validator --check",
        cwd=".",
        policy="project_command",
        returncode=124 if timed_out else returncode,
        stdout="validator stdout",
        stderr="validator stderr",
        duration_seconds=0.125,
        timed_out=timed_out,
        output_truncated=False,
    )


def test_security_scan_workflow_skips_project_validation_baseline() -> None:
    workflow = workflow_asset_service.load_workflow_asset("security-scan")
    assert workflow["validationBaseline"] is False


def test_security_scan_run_persists_baseline_policy(tmp_path: Path) -> None:
    project = tmp_path / "legacy-dotnet-project"
    project.mkdir()
    (project / "Legacy.sln").write_text("Microsoft Visual Studio Solution File\n", encoding="utf-8")

    with patch("app.services.workflow_service.start_workflow_task"):
        with TestClient(app) as client:
            session = client.post("/api/sessions", json={"title": "security", "project_path": str(project)})
            assert session.status_code == 200, session.text
            run = client.post(
                f"/api/sessions/{session.json()['id']}/workflow-runs",
                json={"workflow_id": "security-scan", "requirement": "Scan this project for security issues."},
            )
            assert run.status_code == 200, run.text
            assert run.json()["validation_baseline_required"] is False


def test_validation_phase_uses_cross_platform_command_runner(monkeypatch, tmp_path: Path) -> None:
    captured = []

    async def fake_run(request):
        captured.append(request)
        return _command_result()

    monkeypatch.setattr(validation_plan, "run_command_async", fake_run)
    phase = {
        "id": "dotnet-build",
        "title": ".NET build",
        "category": "build",
        "command": ["dotnet", "build"],
        "required": True,
        "available": True,
    }
    result = asyncio.run(validation_plan._execute_phase(tmp_path, phase, 30))

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert captured[0].shell is False
    assert captured[0].project_root == tmp_path


def test_validation_phase_maps_command_runner_timeout(monkeypatch, tmp_path: Path) -> None:
    async def fake_run(_request):
        return _command_result(timed_out=True)

    monkeypatch.setattr(validation_plan, "run_command_async", fake_run)
    phase = {
        "id": "dotnet-test",
        "title": ".NET tests",
        "category": "test",
        "command": ["dotnet", "test"],
        "required": True,
        "available": True,
    }
    result = asyncio.run(validation_plan._execute_phase(tmp_path, phase, 5))

    assert result["status"] == "failed"
    assert result["error_code"] == "VALIDATION_TIMEOUT"
    assert result["exit_code"] is None


def test_single_validator_api_uses_same_cross_platform_runner(monkeypatch, tmp_path: Path) -> None:
    plan = {
        "id": "custom",
        "title": "Custom",
        "category": "custom",
        "command": ["validator", "--check"],
        "command_text": "validator --check",
        "required": True,
        "available": True,
        "detected_by": ["test"],
    }

    monkeypatch.setattr(validation_registry, "detect_validator_plans", lambda _path: [plan])
    monkeypatch.setattr(validation_registry, "primary_validator", lambda _path: plan)

    async def fake_run(_request):
        return _command_result()

    monkeypatch.setattr(validation_registry, "run_command_async", fake_run)
    result = asyncio.run(validation_registry.execute_validator_plan(tmp_path))

    assert result["status"] == "passed"
    assert result["stdout"] == "validator stdout"


def test_python_validation_function_uses_cross_platform_runner(monkeypatch, tmp_path: Path) -> None:
    async def fake_run(_request):
        return _command_result(returncode=3)

    monkeypatch.setattr(builtin_core, "run_command_async", fake_run)
    result = asyncio.run(
        builtin_core._run_validation_command(
            ["python", "validation.py"],
            cwd=tmp_path,
            timeout_sec=10,
        )
    )

    assert result["returncode"] == 3
    assert result["stderr"] == "validator stderr"


def test_fast_terminal_run_is_reconciled_in_ui() -> None:
    root = Path(__file__).resolve().parents[1]
    runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    event_stream = (root / "static/js/features/event-stream.js").read_text(encoding="utf-8")

    assert '["done", "failed", "cancelled"].includes(run.status)' in runs
    assert "finishWorkflowActivity({ type: run.status })" in runs
    assert "Reconcile on every open" in event_stream
    assert "eventStream.reconcileAfterReconnect(runId);" in event_stream


def test_validator_modules_no_longer_call_asyncio_subprocess_directly() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "app/workflow_runtime/validators/plan.py",
        "app/workflow_runtime/validators/registry.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "asyncio.create_subprocess_exec" not in source
        assert "run_command_async" in source
