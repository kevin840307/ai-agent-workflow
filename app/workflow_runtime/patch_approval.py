from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

from app.core.paths import utc_now, write_text
from app.security.isolated_workspace import changed_project_files, apply_isolated_changes
from app.workflow_runtime.run_diff import build_run_diff, render_run_diff_markdown


def patch_preview(run: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(run["workspace"])
    diff = build_run_diff(run, run_dir)
    original = run.get("original_project_path") or run.get("project_path")
    isolated = run.get("isolated_project_path") or run.get("project_path")
    changed = []
    if original and isolated and original != isolated:
        try:
            changed = changed_project_files(Path(original), Path(isolated))
        except Exception:
            changed = [item.get("path") for item in diff.get("files") or [] if item.get("path")]
    else:
        changed = [item.get("path") for item in diff.get("files") or [] if item.get("path")]
    return {
        "schema": "aiwf.patch-approval.v1",
        "run_id": run.get("id"),
        "mode": run.get("patch_mode") or "auto_apply",
        "status": "pending" if (run.get("patch_mode") in {"review", "dry_run"} and run.get("patch_status") not in {"applied"}) else run.get("patch_status") or "not_required",
        "original_project_path": original,
        "isolated_project_path": isolated,
        "changed_files": changed,
        "approval": {
            "mode": run.get("approval_mode") or "fully_automatic",
            "state": run.get("approval_state") or "not_required",
            "required": (run.get("approval_state") or "not_required") == "pending",
        },
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
    changed = list(files or changed_project_files(Path(original), Path(isolated)))
    written = apply_isolated_changes(Path(original), Path(isolated), changed)
    return {
        "schema": "aiwf.patch-apply-result.v1",
        "run_id": run.get("id"),
        "applied_at": utc_now(),
        "written_files": [str(path) for path in written],
        "changed_files": changed,
    }


__all__ = ["patch_preview", "write_patch_artifacts", "apply_patch"]
