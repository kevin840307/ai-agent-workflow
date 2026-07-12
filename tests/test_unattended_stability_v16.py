from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.security.isolated_workspace import snapshot_project_hashes
from app.services import provider_connectivity_service, workflow_service
from app.workflow.agents.errors import classify_agent_error
from app.workflow_runtime.atomic_delivery import deliver_isolated_changes
from app.workflow_runtime.environment_health import inspect_environment
from app.workflow_runtime.project_validation_profile import create_detected_profile, load_profile, save_profile
from app.workflow_runtime.retry_guard import progress_signature, should_stop_retry


def test_connection_refused_is_transient_and_recoverable():
    result = classify_agent_error("connectex: No connection could be made because the target machine actively refused it")
    assert result["code"] == "TRANSIENT_API_FAILURE"
    assert result["recoverable"] is True
    assert result["strategy"] == "backoff"


def test_wait_for_connectivity_returns_after_endpoint_recovers(monkeypatch, tmp_path: Path):
    states = iter([
        {"state": "offline", "online": False, "endpoints": [{}]},
        {"state": "online", "online": True, "endpoints": [{"reachable": True}]},
    ])

    async def fake_status(*_args, **_kwargs):
        return next(states)

    monkeypatch.setattr(provider_connectivity_service, "connectivity_status", fake_status)
    result = asyncio.run(provider_connectivity_service.wait_for_connectivity(tmp_path, "qwen", timeout_sec=2, poll_sec=0.01))
    assert result["state"] == "online"


def test_progress_aware_retry_rotates_only_when_no_progress(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    from datetime import datetime, timezone
    run = {"created_at": datetime.now(timezone.utc).isoformat(), "steps": [{"key": "build"}]}

    sig = progress_signature(run, project)
    assert should_stop_retry(run, step_key="build", error="same failure", progress=sig)[0] is False
    assert should_stop_retry(run, step_key="build", error="same failure", progress=sig)[0] is False
    stop, _reason, attempt = should_stop_retry(run, step_key="build", error="same failure", progress=sig)
    assert stop is True
    assert attempt["recovery_action"] == "fresh_session"
    assert attempt["hard_stop"] is False

    source.write_text("value = 2\n", encoding="utf-8")
    progressed = progress_signature(run, project)
    stop, _reason, attempt = should_stop_retry(run, step_key="build", error="same failure", progress=progressed)
    assert stop is False
    assert attempt["same_failure_count"] == 1
    assert attempt["progress_detected"] is True


def test_environment_health_is_profile_driven(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.delenv("AIWF_REQUIRED_TEST_TOKEN", raising=False)
    profile = {
        "phases": [{"command": [sys.executable, "-c", "print('ok')"]}],
        "environment": {"requiredEnvironmentVariables": ["AIWF_REQUIRED_TEST_TOKEN"]},
    }
    blocked = inspect_environment(project, profile)
    assert blocked["status"] == "blocked"
    assert "environment:AIWF_REQUIRED_TEST_TOKEN" in blocked["blockers"]
    monkeypatch.setenv("AIWF_REQUIRED_TEST_TOKEN", "present")
    assert inspect_environment(project, profile)["status"] == "ready"


def test_project_validation_profile_becomes_stale_when_descriptor_changes(tmp_path: Path, monkeypatch):
    from app.workflow_runtime import project_validation_profile as profiles

    monkeypatch.setattr(profiles, "PROFILE_ROOT", tmp_path / "profiles")
    project = tmp_path / "project"
    project.mkdir()
    descriptor = project / "pyproject.toml"
    descriptor.write_text("[project]\nname='demo'\n", encoding="utf-8")
    saved = save_profile(create_detected_profile(project))
    assert saved["status"] == "draft"
    descriptor.write_text("[project]\nname='changed'\n", encoding="utf-8")
    loaded = load_profile(project, create=False)
    assert loaded is not None
    assert loaded["status"] == "stale"


def test_atomic_delivery_uses_agent_workspace_and_validates_original(tmp_path: Path):
    original = tmp_path / "original"
    isolated = tmp_path / "isolated"
    workspace = tmp_path / "run"
    original.mkdir(); isolated.mkdir(); workspace.mkdir()
    (original / "value.txt").write_text("before\n", encoding="utf-8")
    (isolated / "value.txt").write_text("after\n", encoding="utf-8")
    profile = {
        "status": "verified",
        "fast_categories": ["custom"],
        "phases": [{
            "id": "verify-value",
            "title": "Verify delivered value",
            "category": "custom",
            "command": [sys.executable, "-c", "from pathlib import Path; assert Path('value.txt').read_text().strip() == 'after'"],
            "required": True,
        }],
    }
    run = {
        "id": "run-1",
        "workspace": str(workspace),
        "project_path": str(isolated),
        "isolated_project_path": str(isolated),
        "original_project_path": str(original),
        "original_project_hashes": snapshot_project_hashes(original),
        "patch_mode": "atomic_apply",
        "project_validation_profile": profile,
        "baseline_validation": {"results": []},
    }
    stored = dict(run)

    async def update_run(_run_id, mutator):
        mutator(stored)
        return dict(stored)

    async def log(_run, _message):
        return None

    result = asyncio.run(deliver_isolated_changes(run, update_run=update_run, log=log))
    assert result is not None and result["status"] == "applied"
    assert (original / "value.txt").read_text(encoding="utf-8") == "after\n"
    assert stored["patch_status"] == "applied"
    assert (workspace / "output" / "atomic-delivery.json").is_file()


def test_unattended_restart_recovery_resumes_only_recoverable_runs(monkeypatch):
    class Store:
        async def read(self):
            return {"runs": [
                {"id": "resume-me", "unattended": True, "restart_recoverable": True, "error_code": "INTERRUPTED", "status": "failed"},
                {"id": "manual", "unattended": False, "restart_recoverable": True, "error_code": "INTERRUPTED", "status": "failed"},
            ]}

    resumed = []

    async def fake_resume(run_id, body=None, *, automatic=False):
        resumed.append((run_id, automatic))
        return {"id": run_id, "status": "queued"}

    monkeypatch.setattr(workflow_service.runtime, "store", Store())
    monkeypatch.setattr(workflow_service.runtime, "running_tasks", {})
    monkeypatch.setattr(workflow_service, "resume_run", fake_resume)
    result = asyncio.run(workflow_service.auto_resume_unattended_runs())
    assert result == [{"id": "resume-me", "status": "queued"}]
    assert resumed == [("resume-me", True)]


def test_v16_ui_has_full_work_surfaces_and_single_cancel_modal_contract():
    root = Path(__file__).resolve().parents[1]
    css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    diagnostics = (root / "static/js/features/diagnostics.js").read_text(encoding="utf-8")
    runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    events = (root / "static/js/features/events.js").read_text(encoding="utf-8")
    assert ".diagnostics-drawer.maximized" in css
    assert "grid-template-columns: clamp(300px, 26vw, 430px) minmax(0, 1fr)" in css
    assert "grid-template-columns: clamp(300px, 27vw, 430px) minmax(0, 1fr)" in css
    assert 'if (run.status === "cancelled")' in runs
    assert "terminateInFlight" in runs
    assert "toggleSize()" in diagnostics
    assert 'ui.on("toggleDiagnosticsSize"' in events
    assert 'ui.on("projectValidationStatus"' not in events
    assert 'unattended: state.advancedMode ? Boolean(state.unattendedMode) : true' in runs


def test_task_context_uses_filesystem_state_not_legacy_file_blocks(tmp_path: Path):
    import json
    from app.workflow_runtime.prompt_builder import PromptBuilder

    project = tmp_path / "project"
    output = tmp_path / "output"
    task_dir = output / "tasks" / "TASK-001"
    project.mkdir(); task_dir.mkdir(parents=True)
    (project / "main.py").write_text("def preserved():\n    return 42\n", encoding="utf-8")
    (task_dir / "build-state.json").write_text(json.dumps({
        "task_id": "TASK-001",
        "phase": "build",
        "files": [{"path": "main.py", "markers": ["preserved"]}],
    }), encoding="utf-8")

    context = PromptBuilder()._current_task_file_context(
        output,
        project,
        {"id": "TASK-002", "index": 2},
    )
    assert "main.py" in context
    assert "def preserved" in context
    source = (Path(__file__).resolve().parents[1] / "app/workflow_runtime/prompt_builder.py").read_text(encoding="utf-8")
    assert "_extract_file_blocks_for_context" not in source
