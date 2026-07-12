from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.security.isolated_workspace import file_sha256
from app.workflow_runtime.artifact_policy import artifact_display_metadata, artifact_visibility
from app.workflow_runtime.patch_approval import (
    apply_patch,
    patch_identity,
    patch_preview,
    partial_validation_evidence_hash,
    selection_hash,
    validation_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, *, file_count: int = 1) -> dict:
    original = tmp_path / "original"
    isolated = tmp_path / "isolated"
    workspace = tmp_path / "workspace"
    original.mkdir()
    isolated.mkdir()
    workspace.mkdir()
    original_hashes: dict[str, str | None] = {}
    for index in range(file_count):
        name = f"file_{index}.txt"
        original_file = original / name
        original_file.write_text("before\n", encoding="utf-8")
        (isolated / name).write_text(f"after {index}\n", encoding="utf-8")
        original_hashes[name] = file_sha256(original_file)
    return {
        "id": "run-v21",
        "workspace": str(workspace),
        "project_path": str(isolated),
        "original_project_path": str(original),
        "isolated_project_path": str(isolated),
        "patch_mode": "review",
        "approval_mode": "manual",
        "approval_state": "pending",
        "original_project_hashes": original_hashes,
        "steps": [
            {
                "key": "validate-contract",
                "status": "passed",
                "config": {
                    "phase": "validating",
                    "evidenceCategory": "validation",
                    "required": True,
                },
            }
        ],
        "validation_results": [
            {
                "key": "validate-contract",
                "status": "passed",
                "executed": True,
                "exit_code": 0,
            }
        ],
    }


def _approve_current(run: dict, files: list[str] | None = None) -> tuple[dict, list[str]]:
    identity = patch_identity(run)
    selected = files or identity["changed_files"]
    run.update(
        {
            "approval_state": "approved",
            "approval_patch_hash": identity["patch_hash"],
            "approval_validation_hash": identity["validation_evidence_hash"],
            "approval_selection_hash": selection_hash(identity["patch_hash"], selected),
            "approval_files": list(selected),
        }
    )
    return identity, selected




def _partial_validation(run: dict, files: list[str], *, marker: str = "first") -> tuple[str, dict]:
    identity = patch_identity(run)
    selected_hash = selection_hash(identity["patch_hash"], files)
    evidence = {
        "schema": "aiwf.partial-patch-validation.v1",
        "run_id": run["id"],
        "patch_hash": identity["patch_hash"],
        "selection_hash": selected_hash,
        "files": list(files),
        "status": "passed",
        "executed": 1,
        "marker": marker,
    }
    evidence["evidence_hash"] = partial_validation_evidence_hash(evidence)
    run.setdefault("partial_patch_validations", {})[selected_hash] = evidence
    return selected_hash, evidence

def test_artifact_classification_ignores_user_controlled_path() -> None:
    misleading = "reports/test-result-final-review-prompt-trace.log"
    assert artifact_visibility(misleading) == "supporting"
    assert artifact_visibility(misleading, category="validation") == "essential"
    assert artifact_visibility(misleading, role="log") == "diagnostic"


def test_unknown_artifact_is_explicitly_unclassified() -> None:
    metadata = artifact_display_metadata(category="not-registered", role="not-registered")
    assert metadata["category"] == "not-registered"
    assert metadata["role"] == "not-registered"
    assert metadata["display_name"] == "未分類產物"
    assert metadata["visibility"] == "supporting"


def test_patch_identity_changes_with_content_and_validation_evidence(tmp_path: Path) -> None:
    run = _run(tmp_path)
    first = patch_identity(run)
    Path(run["isolated_project_path"], "file_0.txt").write_text("different\n", encoding="utf-8")
    second = patch_identity(run)
    assert first["patch_hash"] != second["patch_hash"]

    run["validation_results"][0]["status"] = "failed"
    third = patch_identity(run)
    assert second["validation_evidence_hash"] != third["validation_evidence_hash"]
    assert second["patch_hash"] != third["patch_hash"]


def test_patch_preview_marks_changed_approval_stale(tmp_path: Path) -> None:
    run = _run(tmp_path)
    _approve_current(run)
    assert patch_preview(run)["approval"]["state"] == "approved"
    Path(run["isolated_project_path"], "file_0.txt").write_text("changed after approval\n", encoding="utf-8")
    assert patch_preview(run)["approval"]["state"] == "stale"


@pytest.mark.parametrize(
    ("steps", "results", "expected_code"),
    [
        ([], [], "VALIDATION_NOT_CONFIGURED"),
        ([{"key": "v", "config": {"phase": "validating", "evidenceCategory": "validation", "required": True}}], [], "VALIDATION_NOT_PASSED"),
        ([{"key": "v", "config": {"phase": "validating", "evidenceCategory": "validation", "required": True}}], [{"key": "v", "status": "skipped", "executed": False}], "VALIDATION_NOT_PASSED"),
    ],
)
def test_validation_gate_requires_explicit_executed_evidence(steps: list[dict], results: list[dict], expected_code: str) -> None:
    gate = validation_gate({"steps": steps, "validation_results": results})
    assert gate["passed"] is False
    assert gate["code"] == expected_code


def test_validation_gate_accepts_explicit_passed_result() -> None:
    gate = validation_gate(
        {
            "steps": [{"key": "v", "config": {"phase": "validating", "evidenceCategory": "validation", "required": True}}],
            "validation_results": [{"key": "v", "status": "passed", "executed": True, "exit_code": 0}],
        }
    )
    assert gate["passed"] is True
    assert gate["required_count"] == 1


def test_full_patch_apply_succeeds_with_approved_executed_validation(tmp_path: Path) -> None:
    run = _run(tmp_path)
    identity, selected = _approve_current(run)
    result = apply_patch(run, selected)
    assert result["patch_hash"] == identity["patch_hash"]
    assert result["selection_hash"] == selection_hash(identity["patch_hash"], selected)
    assert Path(run["original_project_path"], "file_0.txt").read_text(encoding="utf-8") == "after 0\n"


def test_full_patch_apply_refuses_missing_validation(tmp_path: Path) -> None:
    run = _run(tmp_path)
    run["steps"] = []
    run["validation_results"] = []
    _approve_current(run)
    with pytest.raises(HTTPException) as error:
        apply_patch(run)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "VALIDATION_NOT_CONFIGURED"


def test_partial_patch_apply_requires_matching_revalidation(tmp_path: Path) -> None:
    run = _run(tmp_path, file_count=2)
    identity, _ = _approve_current(run, ["file_0.txt"])
    expected_selection = selection_hash(identity["patch_hash"], ["file_0.txt"])
    with pytest.raises(HTTPException) as error:
        apply_patch(run, ["file_0.txt"])
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "PARTIAL_PATCH_REVALIDATION_REQUIRED", "selection_hash": expected_selection}


def test_partial_patch_approval_binds_exact_revalidation_evidence(tmp_path: Path) -> None:
    run = _run(tmp_path, file_count=2)
    identity = patch_identity(run)
    selected = ["file_0.txt"]
    selected_hash, evidence = _partial_validation(run, selected, marker="first")
    run.update({
        "approval_state": "approved",
        "approval_patch_hash": identity["patch_hash"],
        "approval_validation_hash": evidence["evidence_hash"],
        "approval_selection_hash": selected_hash,
        "approval_files": selected,
    })
    assert patch_preview(run)["approval"]["state"] == "approved"
    result = apply_patch(run, selected)
    assert result["selection_hash"] == selected_hash
    assert Path(run["original_project_path"], "file_0.txt").read_text(encoding="utf-8") == "after 0\n"
    assert Path(run["original_project_path"], "file_1.txt").read_text(encoding="utf-8") == "before\n"


def test_partial_patch_revalidation_rerun_invalidates_old_approval(tmp_path: Path) -> None:
    run = _run(tmp_path, file_count=2)
    identity = patch_identity(run)
    selected = ["file_0.txt"]
    selected_hash, evidence = _partial_validation(run, selected, marker="first")
    run.update({
        "approval_state": "approved",
        "approval_patch_hash": identity["patch_hash"],
        "approval_validation_hash": evidence["evidence_hash"],
        "approval_selection_hash": selected_hash,
        "approval_files": selected,
    })
    _, rerun = _partial_validation(run, selected, marker="second")
    assert rerun["evidence_hash"] != evidence["evidence_hash"]
    preview = patch_preview(run)
    assert preview["approval"]["state"] == "stale"
    assert preview["approval"]["current_validation_evidence_hash"] == rerun["evidence_hash"]
    with pytest.raises(HTTPException) as error:
        apply_patch(run, selected)
    assert error.value.detail["code"] == "APPROVAL_STALE"


def test_v21_ui_contract_has_one_patch_review_and_no_changes_tab() -> None:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="changesPanel"' not in html
    assert 'data-run-panel="changes"' not in html
    assert 'id="diffDialog"' in html
    assert 'id="patchRejectStep"' in html
    assert 'id="diagnosticPatch"' not in html
    assert "執行產物" in html


def test_patch_review_uses_explicit_hashes_revalidation_and_reject_target() -> None:
    script = (ROOT / "static" / "js" / "features" / "patch-review.js").read_text(encoding="utf-8")
    assert "/patch/validate-selection" in script
    assert "patch_hash" in script
    assert "selection_hash" in script
    assert "evidence_hash" in script
    assert 'action: "approve"' in script
    assert 'action: "reject"' in script
    assert "rejectStep" in script
    assert "producer_step_key" in script
    assert "includes(\"test\")" not in script
    assert "includes(\"review\")" not in script


def test_patch_review_bounds_large_diff_and_remembers_layout_preferences() -> None:
    script = (ROOT / "static" / "js" / "features" / "patch-review.js").read_text(encoding="utf-8")
    storage = (ROOT / "static" / "js" / "core" / "storage.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "workflow-runner.css").read_text(encoding="utf-8")
    assert "DIFF_PAGE_ROWS = 1500" in script
    assert "data-diff-load-more" in script
    assert "patchSidebarWidth" in script and "patchFilesCollapsed" in script
    assert "patchSidebarWidth" in storage and "patchFilesCollapsed" in storage
    assert "loadedRunId" in script and "loadedPatchHash" in script and "rowLimitByFile.clear()" in script
    assert "content-visibility: auto" in css


def test_artifact_viewer_has_segmented_preview_and_storage_summary() -> None:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "features" / "artifacts.js").read_text(encoding="utf-8")
    assert 'id="artifactStorageSummary"' in html
    assert 'id="artifactLoadMore"' in html
    dom = (ROOT / "static" / "js" / "core" / "dom.js").read_text(encoding="utf-8")
    assert 'artifactStorageSummary: "artifactStorageSummary"' in dom
    assert "PREVIEW_CHUNK_CHARS = 500_000" in script
    assert 'ui.byKey("artifactLoadMore")' in script
    assert 'ui.byKey("artifactStorageSummary")' in script


def test_artifact_viewer_does_not_classify_by_filename_keywords() -> None:
    script = (ROOT / "static" / "js" / "features" / "artifacts.js").read_text(encoding="utf-8")
    policy = (ROOT / "app" / "workflow_runtime" / "artifact_policy.py").read_text(encoding="utf-8")
    for token in ('name.includes("test")', 'name.includes("review")', 'name.includes("log")', 'endsWith("spec.md")', 'endsWith("todo.md")'):
        assert token not in script
        assert token not in policy
    assert "producer_step_key" in script
    assert "display_order" in script
    assert "media_type" in script


def test_frontend_cache_version_is_v22() -> None:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "20260712-ui-v20" not in html
    assert "20260712-ui-v22" in html
