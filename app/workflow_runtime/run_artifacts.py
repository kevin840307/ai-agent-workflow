from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text
from app.workflow_runtime.artifact_policy import artifact_display_metadata, artifact_preview_kind, enrich_artifact_records

ARTIFACT_SCHEMA = "aiwf.run-artifacts.v2"
ARTIFACT_METADATA_SCHEMA = "aiwf.artifact-metadata.v2"
STANDARD_DIRS = [
    "steps",
    "diff",
    "validation",
    "patch",
    "reports",
    "console",
    "metadata",
]


def _safe_copy(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _json_or_none(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _content_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _record(
    run_id: str,
    run_dir: Path,
    rel: str,
    *,
    category: str,
    role: str,
    display_name: str | None = None,
    display_order: int | None = None,
    producer_step_key: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    path = run_dir / rel
    defaults = artifact_display_metadata(category=category, role=role)
    guessed_media, _encoding = mimetypes.guess_type(path.name)
    normalized_rel = rel.replace("\\", "/")
    storage_rel = f".workflow/artifacts/{normalized_rel}"
    resolved_media = guessed_media or "text/plain"
    return {
        "id": f"{run_id}:{storage_rel.replace('/', '|')}",
        "run_id": run_id,
        "path": normalized_rel,
        "storage_path": storage_rel,
        "name": Path(rel).name,
        "category": category,
        "role": role,
        "display_name": display_name or defaults["display_name"],
        "display_order": int(display_order if display_order is not None else defaults["display_order"]),
        "producer_step_key": producer_step_key,
        "media_type": resolved_media,
        "preview_kind": artifact_preview_kind(media_type=resolved_media, role=role),
        "metadata_schema": ARTIFACT_METADATA_SCHEMA,
        "size": path.stat().st_size if path.exists() else 0,
        "content_hash": _content_hash(path),
        "exists": path.exists(),
        "visibility": visibility or defaults["visibility"],
        "updated_at": utc_now(),
    }


def _producer_for_artifact(run: dict[str, Any], source_rel: str, role: str) -> str | None:
    normalized = str(source_rel or "").replace("\\", "/")
    for step in run.get("steps") or []:
        config = step.get("config") or {}
        explicit_role = str(config.get("artifactRole") or config.get("artifact_role") or "")
        def values(value: Any) -> list[Any]:
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                return list(value)
            return [value]

        outputs = [*values(config.get("outputs")), *values(config.get("expectedFiles")), config.get("outputFile"), config.get("filename")]
        normalized_outputs: set[str] = set()
        for value in outputs:
            output = str(value or "").replace("\\", "/").strip()
            if output and not output.startswith(("output/", "input/", "prompts/", ".workflow/")):
                output = f"output/{output}"
            if output:
                normalized_outputs.add(output)
        if explicit_role == role or normalized in normalized_outputs:
            return str(step.get("key") or "") or None
    return None


def write_standard_run_artifacts(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Create a stable .workflow/artifacts layout for UI, export, replay, and tests.

    Older workflow code writes useful files directly in `.workflow/`, `output/`,
    and `prompts/`.  This function does not remove those files.  It mirrors the
    important ones into a predictable artifact index so future UI/tools do not
    need to know every legacy filename.
    """
    workflow_dir = run_dir / ".workflow"
    artifacts_dir = workflow_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_mode = os.environ.get("AIWF_ARTIFACT_MODE", "compact").strip().lower()
    active_dirs = STANDARD_DIRS if artifact_mode == "full" else ["diff", "validation", "reports", "metadata"]
    for folder in active_dirs:
        (artifacts_dir / folder).mkdir(parents=True, exist_ok=True)

    copies: list[tuple[str, str, str, str]] = [
        (".workflow/state.json", "metadata/state.json", "metadata", "state"),
        (".workflow/events.jsonl", "metadata/events.jsonl", "metadata", "events"),
        (".workflow/debug-bundle.json", "metadata/debug-bundle.json", "metadata", "debug-bundle"),
        (".workflow/final-report.md", "reports/final-report.md", "report", "final-report"),
        (".workflow/version-metadata.json", "metadata/version-metadata.json", "metadata", "version"),
        (".workflow/run-console.json", "console/run-console.json", "console", "timeline"),
        (".workflow/run-log.md", "console/run-log.md", "console", "log"),
        (".workflow/run-trace.json", "reports/run-trace.json", "report", "trace"),
        (".workflow/run-summary.md", "reports/run-summary.md", "report", "summary"),
        (".workflow/gate-report.json", "reports/gate-report.json", "report", "gate"),
        (".workflow/gate-report.md", "reports/gate-report.md", "report", "gate"),
        (".workflow/run-diff.json", "diff/run-diff.json", "diff", "run-diff"),
        (".workflow/run-diff.md", "diff/run-diff.md", "diff", "run-diff"),
        (".workflow/patch-approval.json", "patch/patch-approval.json", "patch", "approval"),
        (".workflow/patch-approval.md", "patch/patch-approval.md", "patch", "approval"),
        ("output/test-result.md", "validation/test-result.md", "validation", "test"),
        ("output/external-validation-result.md", "validation/external-validation-result.md", "validation", "external-validation"),
        ("output/final-review.md", "reports/final-review.md", "report", "final-review"),
        ("output/verifier-report.json", "reports/verifier-report.json", "report", "verifier"),
    ]

    if artifact_mode != "full":
        compact_roles = {
            "final-report", "summary", "gate", "run-diff", "test",
            "external-validation", "final-review", "verifier",
        }
        copies = [item for item in copies if item[3] in compact_roles]

    records: list[dict[str, Any]] = []
    for src_rel, dst_rel, category, role in copies:
        if _safe_copy(run_dir / src_rel, artifacts_dir / dst_rel):
            records.append(_record(
                str(run.get("id") or ""), artifacts_dir, dst_rel,
                category=category, role=role,
                producer_step_key=_producer_for_artifact(run, src_rel, role),
            ))

    if artifact_mode == "full":
        for step in run.get("steps") or []:
            key = str(step.get("key") or "step")
            safe_key = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in key)
            step_payload = {
                "schema": "aiwf.step-artifact.v1",
                "run_id": run.get("id"),
                "key": key,
                "title": step.get("title") or step.get("name") or key,
                "status": step.get("status"),
                "retry_count": step.get("retry_count") or 0,
                "started_at": step.get("started_at"),
                "ended_at": step.get("ended_at"),
                "error": step.get("error"),
                "error_code": step.get("error_code"),
                "changed_files": step.get("changed_files") or [],
                "events": step.get("events") or [],
            }
            rel = f"steps/{safe_key}.json"
            write_text(artifacts_dir / rel, json.dumps(step_payload, indent=2, ensure_ascii=False))
            records.append(_record(str(run.get("id") or ""), artifacts_dir, rel, category="step", role="step-state", display_name=str(step.get("title") or key), producer_step_key=key))

    # Always emit a compact final report and debug bundle so local users have a
    # stable artifact to export even when the workflow failed early.
    final_report_rel = "reports/final-report.md"
    write_text(artifacts_dir / final_report_rel, render_final_report(run, records))
    records.append(_record(str(run.get("id") or ""), artifacts_dir, final_report_rel, category="report", role="final-report"))
    debug_bundle_rel = "metadata/debug-bundle.json"
    write_text(artifacts_dir / debug_bundle_rel, json.dumps(render_debug_bundle_payload(run, records), indent=2, ensure_ascii=False))
    records.append(_record(str(run.get("id") or ""), artifacts_dir, debug_bundle_rel, category="metadata", role="debug-bundle"))

    records = enrich_artifact_records(records)
    console = _json_or_none(artifacts_dir / "console/run-console.json") or {}
    index = {
        "schema": ARTIFACT_SCHEMA,
        "run_id": run.get("id"),
        "session_id": run.get("session_id"),
        "workflow_id": run.get("workflow_id"),
        "status": run.get("status"),
        "generated_at": utc_now(),
        "layout_root": ".workflow/artifacts",
        "standard_dirs": active_dirs,
        "artifact_mode": artifact_mode,
        "summary": console.get("summary") or {
            "steps_total": len(run.get("steps") or []),
            "retry_total": sum(int(step.get("retry_count") or 0) for step in run.get("steps") or []),
        },
        "records": records,
    }
    write_text(artifacts_dir / "index.json", json.dumps(index, indent=2, ensure_ascii=False))
    if artifact_mode == "full":
        write_text(artifacts_dir / "README.md", render_artifact_readme(index))
    else:
        readme = artifacts_dir / "README.md"
        if readme.exists():
            readme.unlink()
    return index


def render_artifact_readme(index: dict[str, Any]) -> str:
    lines = [
        "# Run Artifacts",
        "",
        f"- Schema: {index.get('schema')}",
        f"- Run ID: {index.get('run_id')}",
        f"- Workflow: {index.get('workflow_id')}",
        f"- Status: {index.get('status')}",
        "",
        "## Standard Layout",
    ]
    for folder in index.get("standard_dirs") or []:
        lines.append(f"- `{folder}/`")
    lines.extend(["", "## Records"])
    records = index.get("records") or []
    if not records:
        lines.append("- No standardized artifacts were generated yet.")
    else:
        for item in records:
            lines.append(f"- `{item.get('path')}` - {item.get('category')} / {item.get('role')}")
    return "\n".join(lines).rstrip() + "\n"


def render_final_report(run: dict[str, Any], records: list[dict[str, Any]] | None = None) -> str:
    steps = run.get("steps") or []
    failed = next((step for step in steps if step.get("status") == "failed"), None)
    lines = [
        "# Workflow Final Report",
        "",
        f"- Run ID: {run.get('id')}",
        f"- Workflow: {run.get('workflow_id') or run.get('workflow_name')}",
        f"- Status: {run.get('status')}",
        f"- Project Path: {run.get('project_path')}",
        f"- Patch Mode: {run.get('patch_mode')}",
        f"- Retry Total: {sum(int(step.get('retry_count') or 0) for step in steps)}",
        f"- Artifacts: {len(records or [])}",
    ]
    if failed:
        lines.extend([
            "",
            "## Failed Step",
            f"- Step: {failed.get('key')}",
            f"- Error Code: {failed.get('error_code')}",
            f"- Error: {failed.get('error')}",
        ])
    lines.extend(["", "## Steps"])
    for step in steps:
        lines.append(f"- `{step.get('key')}`: {step.get('status')} (retry={int(step.get('retry_count') or 0)})")
    return "\n".join(lines).rstrip() + "\n"


def render_debug_bundle_payload(run: dict[str, Any], records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    steps = run.get("steps") or []
    failed = next((step for step in steps if step.get("status") == "failed"), None)
    return {
        "schema": "aiwf.debug-bundle.v2",
        "runId": run.get("id"),
        "sessionId": run.get("session_id"),
        "workflow": run.get("workflow_id") or run.get("workflow_name"),
        "status": run.get("status"),
        "failedStep": (failed or {}).get("key"),
        "failureType": (failed or {}).get("error_code") or run.get("error_code"),
        "retryCount": sum(int(step.get("retry_count") or 0) for step in steps),
        "patchMode": run.get("patch_mode"),
        "patchStatus": run.get("patch_status"),
        "projectPath": run.get("original_project_path") or run.get("project_path"),
        "effectiveProjectPath": run.get("project_path"),
        "workspace": run.get("workspace"),
        "lastError": (failed or {}).get("error") or run.get("error"),
        "artifacts": [item.get("path") for item in (records or [])],
    }


def read_run_artifact_index(run: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(run["workspace"])
    index_path = run_dir / ".workflow" / "artifacts" / "index.json"
    if index_path.exists():
        try:
            return json.loads(index_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass
    return write_standard_run_artifacts(run, run_dir)


__all__ = ["ARTIFACT_SCHEMA", "write_standard_run_artifacts", "read_run_artifact_index", "render_artifact_readme", "render_final_report", "render_debug_bundle_payload"]
