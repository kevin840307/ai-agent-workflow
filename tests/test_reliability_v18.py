from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agents.process_registry import ProcessRegistry, _pid_alive
from app.services.model_circuit_breaker import ModelCircuitBreaker
from app.stores.run_store import FileRunStore
from app.workflow_runtime.failure_normalizer import normalize_failure
from app.workflow_runtime.flaky_tests import classify_attempts, merge_flaky_result
from app.workflow_runtime.progress_evaluator import capture_progress, compare_progress
from app.workflow_runtime.retry_guard import should_stop_retry
from app.workflow_runtime.run_lease import (
    acquire_run_lease,
    attempt_idempotency_key,
    begin_attempt,
    finish_attempt,
    lease_is_expired,
    release_run_lease,
    renew_run_lease,
)
from app.workflow_runtime.validators import plan as validation_plan


def test_failure_normalizer_never_emits_blank_failure() -> None:
    failure = normalize_failure(Exception(), source="adaptive_python_gate", step_key="ai_review")
    assert failure["summary"] == "adaptive_python_gate failed with Exception"
    assert failure["code"]
    assert failure["evidence_hash"]
    assert failure["schema"] == "aiwf.failure.v3"
    assert "aiwf.failure.v2" in failure["compatible_with"]


def test_failure_normalizer_keeps_owner_and_stable_evidence_hash() -> None:
    first = normalize_failure(
        "test code must be separated from production files",
        source="candidate_validation",
        step_key="auto_generation",
        owner_task_id="TASK-001",
        evidence={"files": ["sort_algorithms.py"]},
    )
    second = normalize_failure(
        "test code must be separated from production files",
        source="candidate_validation",
        step_key="auto_generation",
        owner_task_id="TASK-001",
        evidence={"files": ["sort_algorithms.py"]},
    )
    assert first["owner_task_id"] == "TASK-001"
    assert first["evidence_hash"] == second["evidence_hash"]


def test_progress_evaluator_distinguishes_improvement_and_regression(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("value = 1\n", encoding="utf-8")
    previous = capture_progress({"validation_results": [{"required_failures": 4}]}, project)
    improved = capture_progress({"validation_results": [{"required_failures": 1}]}, project)
    comparison = compare_progress(previous, improved)
    assert comparison["improved"] is True
    assert "required_failures:4->1" in comparison["reasons"]

    regressed = capture_progress({"validation_results": [{"required_failures": 6}]}, project)
    comparison = compare_progress(previous, regressed)
    assert comparison["regressed"] is True


def test_progress_aware_retry_keeps_repairing_when_failures_decrease(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("value = 1\n", encoding="utf-8")
    run = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_path": str(project),
        "steps": [{"key": "test"}],
        "validation_results": [{"required_failures": 5}],
    }
    assert should_stop_retry(run, step_key="test", error="same failure")[0] is False
    run["validation_results"].append({"required_failures": 2})
    stop, _, attempt = should_stop_retry(run, step_key="test", error="same failure")
    assert stop is False
    assert attempt["progress_detected"] is True
    assert attempt["progress_state"] == "improved"


def test_run_lease_prevents_duplicate_owner_and_can_expire() -> None:
    run: dict = {}
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    owner_a = {"id": "host:1", "pid": 1}
    owner_b = {"id": "host:2", "pid": 2}
    lease = acquire_run_lease(run, owner_a, ttl_sec=20, now=now)
    assert not lease_is_expired(lease, now=now + timedelta(seconds=19))
    with pytest.raises(RuntimeError, match="held by"):
        acquire_run_lease(run, owner_b, ttl_sec=20, now=now + timedelta(seconds=5))
    renewed = renew_run_lease(run, owner_a, ttl_sec=20, now=now + timedelta(seconds=10))
    assert renewed["expires_at"] > lease["expires_at"]
    assert release_run_lease(run, owner_id="host:2") is False
    assert release_run_lease(run, owner_id="host:1") is True


def test_attempt_idempotency_blocks_duplicate_active_and_reuses_completed() -> None:
    run = {"id": "run-1", "last_checkpoint_id": "cp-1"}
    key = attempt_idempotency_key(run, "build", retry_count=0)
    first = begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-a")
    assert first["status"] == "running"
    with pytest.raises(RuntimeError, match="Duplicate active attempt"):
        begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-b")
    finish_attempt(run, key, status="completed")
    duplicate = begin_attempt(run, step_key="build", idempotency_key=key, owner_id="owner-b")
    assert duplicate["duplicate_completed"] is True


def test_model_circuit_breaker_open_half_open_and_recovery(monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("AIWF_MODEL_CIRCUIT_FAILURES", "2")
        monkeypatch.setenv("AIWF_MODEL_CIRCUIT_COOLDOWN_SEC", "1")
        breaker = ModelCircuitBreaker()
        await breaker.record_failure("qwen", "offline", now=10)
        assert (await breaker.allow("qwen", now=10.1))["allowed"] is True
        opened = await breaker.record_failure("qwen", "offline", now=11)
        assert opened["state"] == "open"
        assert (await breaker.allow("qwen", now=11.5))["allowed"] is False
        probe = await breaker.allow("qwen", now=12.1)
        assert probe["state"] == "half_open" and probe["allowed"] is True and probe["probe"] is True
        assert (await breaker.allow("qwen", now=12.1))["allowed"] is False
        closed = await breaker.record_success("qwen", now=12.2)
        assert closed["state"] == "closed" and closed["failure_count"] == 0
    asyncio.run(scenario())


def test_process_registry_persists_unregisters_and_reaps_orphans(tmp_path: Path) -> None:
    class Proc:
        pid = 12345

    path = tmp_path / "processes.json"
    registry = ProcessRegistry(path)
    registry.register("run-1", Proc(), process_type="agent", command=["qwen", "secret=abc"], cwd=str(tmp_path))
    assert registry.records()[0]["process_type"] == "agent"
    loaded = ProcessRegistry(path)
    assert loaded.records()[0]["pid"] == 12345
    reaped = loaded.reap_orphans(pid_alive=lambda pid: pid == 12345, terminate=lambda pid: pid == 12345)
    assert len(reaped) == 1
    assert loaded.records() == []
    registry.unregister("run-1")
    assert len(registry) == 0


def test_process_registry_pid_probe_is_safe_on_current_platform() -> None:
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(2_000_000_000) is False


def test_flaky_classification_preserves_evidence() -> None:
    evidence = classify_attempts([{"status": "failed"}, {"status": "passed"}, {"status": "passed"}])
    assert evidence["classification"] == "suspected_flaky"
    merged = merge_flaky_result({"status": "failed", "required": True}, [{"status": "passed", "required": True}])
    assert merged["status"] == "passed"
    assert merged["classification"] == "suspected_flaky"
    assert len(merged["attempts"]) == 2


def test_validation_plan_reruns_failed_tests_and_marks_flaky(monkeypatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        phase = {"id": "tests", "title": "Tests", "category": "test", "command": ["fake"], "required": True, "available": True}
        monkeypatch.setattr(validation_plan, "build_validation_plan", lambda *_a, **_k: {"schema": "x", "project_path": str(tmp_path), "phases": [phase]})
        outcomes = iter([
            {**phase, "status": "failed", "exit_code": 1},
            {**phase, "status": "passed", "exit_code": 0},
        ])

        async def fake_execute(*_a, **_k):
            return next(outcomes)

        monkeypatch.setattr(validation_plan, "_execute_phase", fake_execute)
        result = await validation_plan.execute_validation_plan(tmp_path, flaky_retries=2)
        assert result["status"] == "passed"
        assert result["flaky_count"] == 1
        assert result["results"][0]["classification"] == "suspected_flaky"
    asyncio.run(scenario())


def test_validation_plan_stable_failure_remains_blocking(monkeypatch, tmp_path: Path) -> None:
    async def scenario() -> None:
        phase = {"id": "tests", "title": "Tests", "category": "test", "command": ["fake"], "required": True, "available": True}
        monkeypatch.setattr(validation_plan, "build_validation_plan", lambda *_a, **_k: {"schema": "x", "project_path": str(tmp_path), "phases": [phase]})

        async def fake_execute(*_a, **_k):
            return {**phase, "status": "failed", "exit_code": 1}

        monkeypatch.setattr(validation_plan, "_execute_phase", fake_execute)
        result = await validation_plan.execute_validation_plan(tmp_path, flaky_retries=2)
        assert result["status"] == "failed"
        assert result["required_failures"] == 1
        assert result["results"][0]["flaky_evidence"]["classification"] == "stable_failure"
    asyncio.run(scenario())


def test_run_store_state_version_is_monotonic() -> None:
    async def scenario() -> None:
        data = {"runs": [{"id": "r1", "status": "queued", "state_version": 2}]}

        async def read():
            return data

        async def mutate(fn):
            return fn(data)

        store = FileRunStore(read=read, mutate=mutate)
        updated = await store.mutate_run("r1", lambda run: run.update({"status": "running"}))
        assert updated["state_version"] == 3
        updated = await store.mutate_run("r1", lambda run: run.update({"status": "done"}))
        assert updated["state_version"] == 4
    asyncio.run(scenario())


def test_v21_ui_uses_patch_workbench_and_shared_artifact_viewer() -> None:
    root = Path(__file__).resolve().parents[1]
    index = (root / "static/index.html").read_text(encoding="utf-8")
    css = (root / "static/css/workflow-runner.css").read_text(encoding="utf-8")
    runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    patch_review = (root / "static/js/features/patch-review.js").read_text(encoding="utf-8")
    artifacts = (root / "static/js/features/artifacts.js").read_text(encoding="utf-8")
    console = (root / "static/js/features/console.js").read_text(encoding="utf-8")

    assert 'id="openSelectedStepDetail"' in index
    assert 'data-tab="changesPanel"' not in index
    assert 'id="diagnosticPatch"' not in index
    assert 'id="patchReviewFooter"' in index
    assert 'id="approvePatch"' in index and 'id="approveApplyPatch"' in index
    assert 'class="artifact-viewer-layout"' in index
    assert "V21 review/evidence/artifact workspace" in css
    assert "width: calc(100vw - 16px)" in css
    assert "height: calc(100dvh - 16px)" in css
    assert ".patch-review-workbench.focus-mode" in css
    assert ".artifact-viewer-layout" in css
    assert "openSelectedStepDetail()" in runs
    assert "openStepFilesModal(run, step, { preview: true, artifactId })" in runs
    assert "預覽對應文件" in runs
    assert "async function openStepFilesModal(run, step, { preview: shouldPreview = true, artifactId = null } = {})" in artifacts
    assert "stepFilesModalBackdrop" in artifacts
    assert "僅顯示此 Step" in artifacts
    assert "/patch/validate-selection" in patch_review
    assert "patch_hash" in patch_review and "selection_hash" in patch_review
    assert "maxBufferedLines" in console and "earlier lines kept outside the DOM" in console


def test_ui_run_state_gate_rejects_older_snapshots_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    state = (root / "static/js/core/state.js").read_text(encoding="utf-8")
    runs = (root / "static/js/features/runs.js").read_text(encoding="utf-8")
    assert "export function acceptRunSnapshot" in state
    assert "if (version < known) return false" in state
    assert "if (!acceptRunSnapshot(state, run)) return" in runs


def test_read_only_agent_mutations_are_reverted_before_artifact_validation() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/workflow_runtime/agent_step_runner.py").read_text(encoding="utf-8")
    block = source[source.index("if read_only_snapshot is not None:"):source.index("output = result.output")]
    assert "restore_project_content_snapshot" in block
    assert "continuing with artifact validation" in block
    assert 'counters["deterministic_repairs"]' in block
    assert "raise WorkflowError" not in block


def test_runtime_hotspots_are_extracted_without_replacing_executor_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = [
        "app/workflow_runtime/failure_normalizer.py",
        "app/workflow_runtime/progress_evaluator.py",
        "app/workflow_runtime/run_lease.py",
        "app/workflow_runtime/flaky_tests.py",
        "app/services/model_circuit_breaker.py",
        "app/agents/process_registry.py",
    ]
    assert all((root / item).is_file() for item in expected)
    executor = (root / "app/workflow_runtime/executor.py").read_text(encoding="utf-8")
    assert "acquire_run_lease" in executor
    assert "begin_attempt" in executor
    assert "finish_attempt" in executor
    assert "release_run_lease" in executor


def test_reliability_soak_and_chaos_scripts_pass(tmp_path: Path) -> None:
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    soak = subprocess.run(
        [sys.executable, "scripts/run_reliability_soak.py", "--iterations", "40", "--output", str(tmp_path / "soak.json")],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert soak.returncode == 0, soak.stdout + soak.stderr
    assert json.loads((tmp_path / "soak.json").read_text(encoding="utf-8"))["status"] == "PASS"
    chaos = subprocess.run(
        [sys.executable, "scripts/run_chaos_matrix.py", "--output", str(tmp_path / "chaos.json")],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert chaos.returncode == 0, chaos.stdout + chaos.stderr
    report = json.loads((tmp_path / "chaos.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS" and report["passed"] == report["total"]


def test_validator_process_is_registered_and_released(tmp_path: Path) -> None:
    async def scenario() -> None:
        import sys
        from app.agents.process_registry import managed_process_registry
        phase = {
            "id": "registry-check",
            "title": "Registry check",
            "category": "custom",
            "command": [sys.executable, "-c", "print('ok')"],
            "required": True,
            "available": True,
        }
        before = {item["key"] for item in managed_process_registry.records()}
        result = await validation_plan._execute_phase(tmp_path, phase, 10)
        after = {item["key"] for item in managed_process_registry.records()}
        assert result["status"] == "passed"
        assert after == before
    asyncio.run(scenario())


def test_atomic_delivery_is_idempotent_after_success(tmp_path: Path) -> None:
    async def scenario() -> None:
        import sys
        from app.security.isolated_workspace import snapshot_project_hashes
        from app.workflow_runtime.atomic_delivery import deliver_isolated_changes

        original = tmp_path / "original"
        isolated = tmp_path / "isolated"
        workspace = tmp_path / "run"
        original.mkdir(); isolated.mkdir(); workspace.mkdir()
        (original / "value.txt").write_text("before\n", encoding="utf-8")
        (isolated / "value.txt").write_text("after\n", encoding="utf-8")
        run = {
            "id": "atomic-idempotent",
            "workspace": str(workspace),
            "project_path": str(isolated),
            "isolated_project_path": str(isolated),
            "original_project_path": str(original),
            "original_project_hashes": snapshot_project_hashes(original),
            "patch_mode": "atomic_apply",
            "project_validation_profile": {
                "fast_categories": ["custom"],
                "phases": [{
                    "id": "verify", "title": "Verify", "category": "custom",
                    "command": [sys.executable, "-c", "from pathlib import Path; assert Path('value.txt').read_text().strip() == 'after'"],
                    "required": True,
                }],
            },
            "baseline_validation": {"results": []},
        }
        stored = dict(run)
        updates = 0

        async def update(_run_id, mutator):
            nonlocal updates
            updates += 1
            mutator(stored)
            return dict(stored)

        async def log(_run, _message):
            return None

        first = await deliver_isolated_changes(run, update_run=update, log=log)
        first_updates = updates
        second = await deliver_isolated_changes(run, update_run=update, log=log)
        assert first["status"] == "applied" and second["status"] == "applied"
        assert updates == first_updates
        assert stored["atomic_delivery_transaction"]["status"] == "applied"
        assert (original / "value.txt").read_text(encoding="utf-8") == "after\n"
    asyncio.run(scenario())
