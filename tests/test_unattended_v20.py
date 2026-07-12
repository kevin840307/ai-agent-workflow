from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.persistence.sqlite_store import SQLiteStore
from app.security.isolated_workspace import create_isolated_project_copy, file_sha256
from app.services.model_circuit_breaker import provider_circuit_key
from app.services.validation_script_service import generate_validation_script
from app.workflow_runtime.autopilot_policy import evaluate_delivery_validation
from app.workflow_runtime.delivery_journal import (
    apply_delivery_journal,
    load_delivery_journal,
    prepare_delivery_journal,
    rollback_delivery_journal,
)
from app.workflow_runtime.run_lease import (
    RunLeaseConflict,
    acquire_run_lease,
    assert_run_lease,
)


def _delivery_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    original = root / "original"
    isolated = root / "isolated"
    backup = root / "backup"
    journal = root / "delivery.json"
    original.mkdir()
    isolated.mkdir()
    (original / "a.txt").write_text("old-a", encoding="utf-8")
    (original / "b.txt").write_text("old-b", encoding="utf-8")
    (isolated / "a.txt").write_text("new-a", encoding="utf-8")
    (isolated / "b.txt").write_text("new-b", encoding="utf-8")
    return original, isolated, backup, journal


@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_delivery_journal_rolls_back_after_every_persist_boundary(tmp_path: Path, crash_at: int) -> None:
    original, isolated, backup, journal_path = _delivery_fixture(tmp_path)
    prepared = prepare_delivery_journal(
        original,
        isolated,
        ["a.txt", "b.txt"],
        baseline_hashes={"a.txt": file_sha256(original / "a.txt"), "b.txt": file_sha256(original / "b.txt")},
        backup_dir=backup,
        transaction_id="tx-boundary",
        run_id="run-boundary",
        fencing_token=7,
        journal_path=journal_path,
    )
    calls = 0

    def crash(_journal: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == crash_at:
            raise RuntimeError("simulated controller crash")

    with pytest.raises(RuntimeError, match="simulated controller crash"):
        apply_delivery_journal(prepared, journal_path=journal_path, on_persist=crash)

    recovered = load_delivery_journal(journal_path)
    assert recovered is not None
    rollback_delivery_journal(recovered, journal_path=journal_path)
    assert (original / "a.txt").read_text(encoding="utf-8") == "old-a"
    assert (original / "b.txt").read_text(encoding="utf-8") == "old-b"
    assert load_delivery_journal(journal_path)["status"] == "rolled_back"


def test_delivery_journal_detects_replace_before_operation_state_persist(tmp_path: Path) -> None:
    original, isolated, backup, journal_path = _delivery_fixture(tmp_path)
    prepared = prepare_delivery_journal(
        original,
        isolated,
        ["a.txt", "b.txt"],
        baseline_hashes={"a.txt": file_sha256(original / "a.txt"), "b.txt": file_sha256(original / "b.txt")},
        backup_dir=backup,
        transaction_id="tx-after-replace",
        run_id="run-after-replace",
        journal_path=journal_path,
    )
    shutil.copy2(isolated / "a.txt", original / "a.txt")
    assert prepared["operations"][0]["status"] == "prepared"
    rollback_delivery_journal(prepared, journal_path=journal_path)
    assert (original / "a.txt").read_text(encoding="utf-8") == "old-a"
    assert (original / "b.txt").read_text(encoding="utf-8") == "old-b"


def test_autopilot_rejects_skipped_or_missing_required_validation() -> None:
    run = {"patch_mode": "atomic_apply", "autopilot_mode": "safe_apply", "project_validation_profile": {"status": "verified"}}
    skipped = evaluate_delivery_validation(
        run,
        {"status": "skipped", "executed": 1, "results": [{"id": "tests", "required": True, "status": "skipped"}]},
    )
    assert skipped["allowed"] is False
    assert any("did not pass" in item for item in skipped["errors"])
    missing = evaluate_delivery_validation(run, {"status": "passed", "executed": 0, "results": []})
    assert missing["allowed"] is False
    assert any("did not execute" in item for item in missing["errors"])


def test_run_lease_fencing_rejects_stale_controller() -> None:
    run: dict = {}
    start = datetime(2026, 7, 12, tzinfo=timezone.utc)
    first = acquire_run_lease(run, {"instance_id": "controller-a"}, ttl_sec=10, now=start)
    second = acquire_run_lease(run, {"instance_id": "controller-b"}, ttl_sec=10, now=start + timedelta(seconds=11))
    assert second["fencing_token"] > first["fencing_token"]
    with pytest.raises(RunLeaseConflict):
        assert_run_lease(
            run,
            owner_id="controller-a",
            fencing_token=first["fencing_token"],
            now=start + timedelta(seconds=12),
        )


def test_circuit_key_is_endpoint_model_scoped() -> None:
    class Agent:
        name = "qwen"

        def __init__(self, base_url: str, model: str) -> None:
            self.base_url = base_url
            self.model = model

        def health(self) -> dict:
            return {"type": "openai-compatible", "base_url": self.base_url, "model": self.model, "bin": "qwen"}

    first = provider_circuit_key(Agent("http://127.0.0.1:8080/v1", "model-a"), SimpleNamespace(metadata={}))
    second = provider_circuit_key(Agent("http://127.0.0.1:8081/v1", "model-a"), SimpleNamespace(metadata={}))
    third = provider_circuit_key(Agent("http://127.0.0.1:8080/v1", "model-b"), SimpleNamespace(metadata={}))
    assert len({first, second, third}) == 3


def test_isolated_workspace_preserves_project_agent_config_and_uses_project_copy_as_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "run"
    (project / ".qwen").mkdir(parents=True)
    (project / ".qwen" / "PROJECT_INSTRUCTIONS.md").write_text("project context", encoding="utf-8")
    (project / ".opencode").mkdir()
    (project / ".opencode" / "config.json").write_text("{}", encoding="utf-8")
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    copied = create_isolated_project_copy(project, workspace, strategy="copy")
    assert copied == workspace.resolve() / "agent-project"
    assert (copied / ".qwen" / "PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8") == "project context"
    assert (copied / ".opencode" / "config.json").is_file()


def test_workspace_policy_can_include_dependency_directories(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "run"
    (project / ".ai-workflow").mkdir(parents=True)
    (project / ".ai-workflow" / "workspace-policy.json").write_text(
        json.dumps({"strategy": "copy", "includeDependencyDirs": True, "minFreeBytes": 0}), encoding="utf-8"
    )
    (project / "node_modules" / "dep").mkdir(parents=True)
    (project / "node_modules" / "dep" / "index.js").write_text("module.exports = 1", encoding="utf-8")
    copied = create_isolated_project_copy(project, workspace)
    assert (copied / "node_modules" / "dep" / "index.js").is_file()


def test_sqlite_v2_database_migrates_event_key_before_index(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE store_documents (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)")
        conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
        conn.execute(
            "CREATE TABLE run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, step_key TEXT, event_type TEXT, message TEXT, occurred_at TEXT, payload_json TEXT NOT NULL)"
        )
    store = SQLiteStore(path, default_project_path=lambda: "", default_steps=lambda: [])
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(run_events)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(run_events)")}
    assert "event_key" in columns
    assert "idx_events_key" in indexes
    compacted = store.compact_sync()
    assert compacted["database_bytes_after"] > 0


def test_contracts_declare_machine_readable_phase_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "data" / "ai-workflow" / "contracts").rglob("*.yaml"):
        contract = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        assert contract.get("phase"), path
        assert contract.get("sessionRole"), path
        if contract.get("phase") == "validating":
            assert contract.get("evidenceCategory") == "validation", path


def test_ui_uses_collapsed_launcher_and_large_diff_dialog_without_maximize_button() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    runs = (root / "static" / "js" / "features" / "runs.js").read_text(encoding="utf-8")
    events = (root / "static" / "js" / "features" / "events.js").read_text(encoding="utf-8")
    assert 'id="expandRunCenter"' in html
    assert 'id="diffDialog"' in html
    assert 'id="diffDialogFileList"' in html
    assert 'id="diffDialogContent"' in html
    assert "toggleRunCenterSize" not in html + runs + events
    assert "openDiffDialog" in runs and "closeDiffDialog" in runs



def test_validation_script_generator_requires_explicit_contract_and_never_infers_semantics() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="expectedFiles is required"):
        generate_validation_script(
            "Create sorting_algorithms.py with bubble_sort",
            "bubble_sort should return a sorted list",
        )
    script = generate_validation_script(
        "Arbitrary free-form requirement text that must not be parsed",
        expected_files=["module.py"],
        expected_symbols=["run"],
    )
    assert "module.py" in script
    assert "run" in script
    assert "sorting_algorithms.py" not in script
    assert "bubble_sort" not in script

def test_controller_does_not_infer_workflow_semantics_from_requirement_keywords() -> None:
    root = Path(__file__).resolve().parents[1]
    selected = [
        root / "app/auto_workflow/orchestrator.py",
        root / "app/workflow_runtime/complexity.py",
        root / "app/workflow_runtime/risk_engine.py",
        root / "app/workflow_runtime/scope_control.py",
        root / "app/services/optimization_service.py",
        root / "app/services/validation_script_service.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in selected)
    forbidden = ["DEV_PATTERNS", "ASK_PATTERNS", "NEW_PROJECT_PATTERNS", '"review" in str(item.get("key"', "requirement.lower()", "raw_requirement.lower()", "function_markers", "sorting_algorithms.py"]
    assert all(token not in source for token in forbidden)


def test_markdown_workflow_summary_is_structural_not_keyword_classified(tmp_path: Path) -> None:
    from app.auto_workflow.orchestrator import extract_user_instructions

    doc = tmp_path / "flow.md"
    doc.write_text("# Arbitrary Heading\n\n1. Zebra item\n- Opaque bullet\nPlain prose containing must test 驗證 should not be classified.\n", encoding="utf-8")
    summary = extract_user_instructions("Use flow.md", tmp_path)["workflow_md_refs"][0]["summary"]
    assert summary["required_phases"] == ["# Arbitrary Heading", "1. Zebra item"]
    assert summary["must_follow_rules"] == ["- Opaque bullet"]
    assert all("Plain prose" not in item for item in summary["required_phases"] + summary["must_follow_rules"])


def test_regression_case_id_uses_explicit_workflow_input_not_requirement_text(tmp_path: Path) -> None:
    from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext
    from app.workflow_runtime.builtin_functions.core import collect_regression_context

    output = tmp_path / "output"
    output.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirement.md").write_text("Requirement mentions CASE-999 but it must not control identity.", encoding="utf-8")
    ctx = WorkflowFunctionContext(
        run={"id": "run", "workspace": str(workspace), "workflow_inputs": {"caseId": "WORKITEM0042"}},
        output_dir=output,
        project_dir=tmp_path,
        root_dir=tmp_path,
        read_text=lambda path: path.read_text(encoding="utf-8") if path.is_file() else "",
        write_text=lambda path, text: (path.parent.mkdir(parents=True, exist_ok=True), path.write_text(text, encoding="utf-8"))[1],
        log=lambda *_args, **_kwargs: None,
        refresh_artifacts=lambda *_args, **_kwargs: None,
    )
    collect_regression_context(ctx)
    text = (output / "regression-context.md").read_text(encoding="utf-8")
    assert "Case ID: WORKITEM0042" in text
    assert "Case ID: CASE-999" not in text


def test_general_plan_gate_uses_manifest_contract_not_todo_keywords(tmp_path: Path) -> None:
    import asyncio
    import json
    from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext
    from app.workflow_runtime.builtin_functions.core import validate_general_auto_plan

    output = tmp_path / "output"
    output.mkdir()
    (output / "todo.md").write_text("Opaque prose with no special phase words.", encoding="utf-8")
    (output / "task-manifest.json").write_text(
        json.dumps({
            "status": "READY",
            "schema_version": 2,
            "tasks": [{
                "id": "TASK-001",
                "title": "Opaque title",
                "prompt": "Perform the explicit task contract.",
                "acceptance": ["Machine-readable acceptance item"],
            }],
        }),
        encoding="utf-8",
    )
    async def noop(*_args, **_kwargs):
        return None
    ctx = WorkflowFunctionContext(
        run={"id": "run", "workspace": str(tmp_path)},
        output_dir=output,
        project_dir=tmp_path,
        root_dir=tmp_path,
        read_text=lambda path: path.read_text(encoding="utf-8") if path.is_file() else "",
        write_text=lambda path, text: path.write_text(text, encoding="utf-8"),
        log=noop,
        refresh_artifacts=noop,
    )
    validate_general_auto_plan(ctx)
    assert "Status: PASS" in (output / "implementation-review.md").read_text(encoding="utf-8")
