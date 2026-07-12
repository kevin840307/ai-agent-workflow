from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

from app.core.paths import utc_now, write_text
from app.security.isolated_workspace import (
    apply_isolated_changes_atomic,
    changed_project_files,
    file_sha256,
)
from app.workflow_runtime.run_diff import build_run_diff, render_run_diff_markdown
from app.workflow_runtime.step_metadata import is_validation_step


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_files(values: Iterable[str] | None) -> list[str]:
    normalized: set[str] = set()
    for value in values or []:
        raw = str(value or "").replace("\\", "/").strip()
        while raw.startswith("./"):
            raw = raw[2:]
        if not raw or raw.startswith("/") or ".." in Path(raw).parts:
            raise HTTPException(status_code=400, detail=f"Unsafe patch path: {value}")
        normalized.add(Path(raw).as_posix())
    return sorted(normalized)


def _file_manifest(root: Path, files: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in _normalized_files(files):
        path = root / rel
        rows.append({
            "path": rel,
            "operation": "write" if path.is_file() else "delete",
            "content_hash": file_sha256(path),
            "size": path.stat().st_size if path.is_file() else 0,
        })
    return rows


def validation_evidence_payload(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "validation_results": run.get("validation_results") or [],
        "validation_steps": [
            {
                "key": step.get("key"),
                "status": step.get("status"),
                "retry_count": int(step.get("retry_count") or 0),
                "error_code": step.get("error_code"),
                "ended_at": step.get("ended_at"),
            }
            for step in run.get("steps") or []
            if (step.get("config") or {}).get("evidenceCategory") == "validation"
            or (step.get("config") or {}).get("evidence_category") == "validation"
            or step.get("evidence_category") == "validation"
        ],
        "profile": {
            "status": (run.get("project_validation_profile") or {}).get("status"),
            "updated_at": (run.get("project_validation_profile") or {}).get("updated_at"),
            "content_hash": (run.get("project_validation_profile") or {}).get("content_hash"),
        },
    }


def validation_evidence_hash(run: dict[str, Any]) -> str:
    return _canonical_hash(validation_evidence_payload(run))


def partial_validation_evidence_hash(evidence: dict[str, Any] | None) -> str | None:
    """Hash one exact Partial Patch validation record.

    The persisted ``evidence_hash`` field is excluded from its own digest. A
    repeated validation therefore creates a new approval boundary even when
    the final status remains PASS.
    """
    if not isinstance(evidence, dict) or not evidence:
        return None
    payload = {key: value for key, value in evidence.items() if key != "evidence_hash"}
    return _canonical_hash(payload)


def selection_validation_evidence_hash(
    run: dict[str, Any],
    patch_hash: str,
    files: Iterable[str],
    *,
    full_files: Iterable[str],
) -> str | None:
    selected = _normalized_files(files)
    complete = _normalized_files(full_files)
    if set(selected) == set(complete):
        return validation_evidence_hash(run)
    selected_hash = selection_hash(patch_hash, selected)
    evidence = (run.get("partial_patch_validations") or {}).get(selected_hash)
    return partial_validation_evidence_hash(evidence)


def validation_gate(run: dict[str, Any]) -> dict[str, Any]:
    """Evaluate required validation from explicit step contracts.

    Step titles, artifact names, requirement text, and prompt content are never
    inspected.  Only the validation step contract and its persisted result are
    authoritative.
    """
    results_by_key = {
        str(item.get("key") or ""): item
        for item in run.get("validation_results") or []
        if isinstance(item, dict) and item.get("key")
    }
    required_steps: list[dict[str, Any]] = []
    for step in run.get("steps") or []:
        if not is_validation_step(step):
            continue
        config = step.get("config") if isinstance(step.get("config"), dict) else {}
        if bool(config.get("required", config.get("validationRequired", True))):
            required_steps.append(step)
    rows: list[dict[str, Any]] = []
    for step in required_steps:
        key = str(step.get("key") or "")
        result = results_by_key.get(key) or {}
        status = str(result.get("status") or step.get("status") or "pending")
        executed = bool(result.get("executed")) or result.get("exit_code") is not None or (bool(result) and status in {"passed", "passed_with_baseline", "failed"})
        rows.append({"key": key, "status": status, "executed": executed})
    passed = bool(rows) and all(row["executed"] and row["status"] in {"passed", "passed_with_baseline"} for row in rows)
    return {
        "passed": passed,
        "required_count": len(rows),
        "rows": rows,
        "code": None if passed else ("VALIDATION_NOT_CONFIGURED" if not rows else "VALIDATION_NOT_PASSED"),
    }


def selection_hash(patch_hash: str, files: Iterable[str]) -> str:
    return _canonical_hash({"patch_hash": patch_hash, "files": _normalized_files(files)})


def patch_identity(run: dict[str, Any], changed: Iterable[str] | None = None) -> dict[str, Any]:
    original = Path(str(run.get("original_project_path") or run.get("project_path") or "")).expanduser().resolve()
    isolated = Path(str(run.get("isolated_project_path") or run.get("project_path") or "")).expanduser().resolve()
    files = _normalized_files(changed if changed is not None else changed_project_files(original, isolated))
    manifest = _file_manifest(isolated, files)
    evidence_hash = validation_evidence_hash(run)
    patch_hash = _canonical_hash({"files": manifest, "validation_evidence_hash": evidence_hash})
    return {
        "patch_hash": patch_hash,
        "validation_evidence_hash": evidence_hash,
        "changed_files": files,
        "file_manifest": manifest,
        "full_selection_hash": selection_hash(patch_hash, files),
    }


def _file_ownership(run: dict[str, Any], files: Iterable[str]) -> dict[str, str | None]:
    owners: dict[str, str | None] = {rel: None for rel in _normalized_files(files)}
    for step in run.get("steps") or []:
        key = str(step.get("key") or "").strip() or None
        for raw in step.get("changed_files") or []:
            rel = str(raw.get("path") if isinstance(raw, dict) else raw).replace("\\", "/")
            if rel in owners:
                owners[rel] = key
    for checkpoint in run.get("task_checkpoints") or []:
        key = str(checkpoint.get("step_key") or "").strip() or None
        for raw in checkpoint.get("changed_files") or []:
            rel = str(raw or "").replace("\\", "/")
            if rel in owners:
                owners[rel] = key
    return owners


def patch_preview(run: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(run["workspace"])
    diff = build_run_diff(run, run_dir)
    original = run.get("original_project_path") or run.get("project_path")
    isolated = run.get("isolated_project_path") or run.get("project_path")
    changed: list[str]
    if original and isolated and original != isolated:
        try:
            changed = changed_project_files(Path(original), Path(isolated))
        except Exception:
            changed = [item.get("path") for item in diff.get("files") or [] if item.get("path")]
    else:
        changed = [item.get("path") for item in diff.get("files") or [] if item.get("path")]
    identity = patch_identity(run, changed)
    approval_state = str(run.get("approval_state") or "not_required")
    approval_patch_hash = run.get("approval_patch_hash")
    approval_validation_hash = run.get("approval_validation_hash")
    approved_files = _normalized_files(run.get("approval_files") or identity["changed_files"])
    approved_selection_hash = run.get("approval_selection_hash")
    current_selection_hash = selection_hash(identity["patch_hash"], approved_files)
    current_approval_validation_hash = selection_validation_evidence_hash(
        run,
        identity["patch_hash"],
        approved_files,
        full_files=identity["changed_files"],
    )
    stale = approval_state == "approved" and (
        approval_patch_hash != identity["patch_hash"]
        or approval_validation_hash != current_approval_validation_hash
        or approved_selection_hash != current_selection_hash
    )
    effective_approval_state = "stale" if stale else approval_state
    ownership = _file_ownership(run, identity["changed_files"])
    partial_validations = run.get("partial_patch_validations") or {}
    return {
        "schema": "aiwf.patch-approval.v2",
        "run_id": run.get("id"),
        "mode": run.get("patch_mode") or "auto_apply",
        "status": "pending" if (run.get("patch_mode") in {"review", "dry_run"} and run.get("patch_status") not in {"applied"}) else run.get("patch_status") or "not_required",
        "original_project_path": original,
        "isolated_project_path": isolated,
        **identity,
        "files": [{**row, "producer_step_key": ownership.get(row["path"])} for row in identity["file_manifest"]],
        "approval": {
            "mode": run.get("approval_mode") or "fully_automatic",
            "state": effective_approval_state,
            "required": (run.get("approval_state") or "not_required") == "pending" or stale,
            "patch_hash": approval_patch_hash,
            "validation_evidence_hash": approval_validation_hash,
            "current_validation_evidence_hash": current_approval_validation_hash,
            "selection_hash": approved_selection_hash,
            "files": approved_files,
            "decided_at": run.get("approval_decided_at"),
            "reason": run.get("approval_reason"),
            "reason_code": run.get("approval_reason_code"),
        },
        "partial_validations": partial_validations,
        "diff": diff,
        "markdown": render_run_diff_markdown(diff),
    }


def write_patch_artifacts(run: dict[str, Any]) -> dict[str, Any]:
    preview = patch_preview(run)
    workflow_dir = Path(run["workspace"]) / ".workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    serializable = {key: value for key, value in preview.items() if key != "markdown"}
    write_text(workflow_dir / "patch-approval.json", json.dumps(serializable, indent=2, ensure_ascii=False))
    write_text(workflow_dir / "patch-approval.md", preview["markdown"])
    return preview


def apply_patch(run: dict[str, Any], files: Iterable[str] | None = None) -> dict[str, Any]:
    mode = run.get("patch_mode") or "auto_apply"
    original = run.get("original_project_path")
    isolated = run.get("isolated_project_path") or run.get("project_path")
    if mode not in {"review", "dry_run"} or not original or not isolated or original == isolated:
        raise HTTPException(status_code=400, detail="This run does not use an isolated patch approval workspace.")
    identity = patch_identity(run)
    selected = _normalized_files(files or identity["changed_files"])
    if not selected:
        raise HTTPException(status_code=400, detail="Select at least one patch file.")
    unknown = sorted(set(selected) - set(identity["changed_files"]))
    if unknown:
        raise HTTPException(status_code=400, detail={"code": "PATCH_SELECTION_INVALID", "files": unknown})
    selected_hash = selection_hash(identity["patch_hash"], selected)
    if run.get("approval_state") != "approved":
        raise HTTPException(status_code=409, detail={"code": "APPROVAL_REQUIRED", "message": "Approve the current patch selection before applying."})
    if run.get("approval_patch_hash") != identity["patch_hash"]:
        raise HTTPException(status_code=409, detail={"code": "APPROVAL_STALE", "message": "Patch changed after approval."})
    if run.get("approval_selection_hash") != selected_hash:
        raise HTTPException(status_code=409, detail={"code": "APPROVAL_SELECTION_MISMATCH", "message": "The approved file selection does not match the apply request."})
    if set(selected) != set(identity["changed_files"]):
        validation = (run.get("partial_patch_validations") or {}).get(selected_hash) or {}
        if (
            validation.get("patch_hash") != identity["patch_hash"]
            or validation.get("selection_hash") != selected_hash
            or validation.get("status") not in {"passed", "passed_with_baseline"}
            or not validation.get("executed")
        ):
            raise HTTPException(status_code=409, detail={"code": "PARTIAL_PATCH_REVALIDATION_REQUIRED", "selection_hash": selected_hash})
        current_validation_hash = partial_validation_evidence_hash(validation)
    else:
        gate = validation_gate(run)
        if not gate["passed"]:
            raise HTTPException(status_code=409, detail={"code": gate["code"], "message": "Required validation evidence must be executed and passed before apply.", "validation": gate})
        current_validation_hash = identity["validation_evidence_hash"]
    if not current_validation_hash or run.get("approval_validation_hash") != current_validation_hash:
        raise HTTPException(status_code=409, detail={"code": "APPROVAL_STALE", "message": "Validation evidence changed after approval."})
    result = apply_isolated_changes_atomic(
        Path(original),
        Path(isolated),
        selected,
        baseline_hashes=dict(run.get("original_project_hashes") or {}),
        backup_dir=Path(run["workspace"]) / ".workflow" / "patch-backup" / selected_hash,
    )
    return {
        "schema": "aiwf.patch-apply-result.v2",
        "run_id": run.get("id"),
        "applied_at": utc_now(),
        "patch_hash": identity["patch_hash"],
        "selection_hash": selected_hash,
        "written_files": result.get("written_files") or [],
        "deleted_files": result.get("deleted_files") or [],
        "changed_files": selected,
        "rollback_manifest": result.get("rollback_manifest") or [],
    }


__all__ = [
    "patch_preview",
    "patch_identity",
    "selection_hash",
    "validation_evidence_hash",
    "partial_validation_evidence_hash",
    "selection_validation_evidence_hash",
    "validation_gate",
    "write_patch_artifacts",
    "apply_patch",
]
