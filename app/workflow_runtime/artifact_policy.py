from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.core.paths import utc_now, write_text

ESSENTIAL_ROLES = {
    "final-report",
    "summary",
    "gate",
    "run-diff",
    "test",
    "external-validation",
    "final-review",
    "verifier",
}
DIAGNOSTIC_CATEGORIES = {"console", "metadata", "step", "patch", "prompt", "debug"}


def artifact_visibility(path: str, *, category: str | None = None, role: str | None = None) -> str:
    normalized = str(path or "").replace("\\", "/")
    role = str(role or "")
    category = str(category or "")
    if role in ESSENTIAL_ROLES:
        return "essential"
    if normalized.endswith("final-report.md") or normalized.endswith("run-summary.md"):
        return "essential"
    if any(token in normalized for token in ("gate-report", "test-result", "validation-result", "run-diff", "final-review", "verifier-report")):
        return "essential"
    if category in DIAGNOSTIC_CATEGORIES or any(token in normalized for token in ("prompt", "console", "events", "state.json", "debug-bundle", "repair-policy", "trace")):
        return "diagnostic"
    return "supporting"


def enrich_artifact_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in records:
        row = dict(item)
        row["visibility"] = artifact_visibility(
            str(row.get("path") or row.get("name") or ""),
            category=row.get("category"),
            role=row.get("role"),
        )
        enriched.append(row)
    return enriched


def filter_artifacts(records: Iterable[dict[str, Any]], view: str = "essential") -> list[dict[str, Any]]:
    rows = enrich_artifact_records(records)
    view = str(view or "essential").lower()
    if view in {"all", "diagnostic", "debug"}:
        return rows
    if view == "supporting":
        return [row for row in rows if row.get("visibility") in {"essential", "supporting"}]
    return [row for row in rows if row.get("visibility") == "essential"]


def _diagnostic_paths(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for root_name in ("prompts", ".workflow"):
        root = run_dir / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(run_dir).as_posix()
            if rel in {".workflow/artifacts/diagnostics.zip", ".workflow/artifacts/index.json"}:
                continue
            if root_name == ".workflow" and not any(
                token in rel for token in ("run-log", "events", "state", "trace", "debug", "repair-policy", "prompt", "console", "patch")
            ):
                continue
            candidates.append(path)
    return sorted(set(candidates))


def compact_run_diagnostics(run: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Pack verbose diagnostics into one archive after a terminal run.

    The source files remain in place by default because replay/recovery tools may
    still need them. Set AIWF_PRUNE_DIAGNOSTIC_FILES=1 to remove only redundant
    mirrored files under `.workflow/artifacts/{steps,console,metadata,patch}`.
    """
    if run.get("status") not in {"done", "failed", "cancelled"} and not force:
        return {"compacted": False, "reason": "run is active"}
    run_dir = Path(str(run.get("workspace") or ""))
    if not run_dir.exists():
        return {"compacted": False, "reason": "workspace missing"}
    artifact_root = run_dir / ".workflow" / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    archive = artifact_root / "diagnostics.zip"
    paths = _diagnostic_paths(run_dir)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            try:
                zf.write(path, path.relative_to(run_dir).as_posix())
            except OSError:
                continue
    manifest = {
        "schema": "aiwf.artifact-compaction.v1",
        "run_id": run.get("id"),
        "generated_at": utc_now(),
        "archive": ".workflow/artifacts/diagnostics.zip",
        "file_count": len(paths),
        "size_bytes": archive.stat().st_size if archive.exists() else 0,
        "pruned": False,
    }
    if os.environ.get("AIWF_PRUNE_DIAGNOSTIC_FILES", "0").strip().lower() in {"1", "true", "yes", "on"}:
        for folder in ("steps", "console", "metadata", "patch"):
            target = artifact_root / folder
            if not target.exists():
                continue
            for path in sorted(target.rglob("*"), reverse=True):
                try:
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                except OSError:
                    continue
        manifest["pruned"] = True
    write_text(artifact_root / "compaction.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return {"compacted": True, **manifest}


__all__ = [
    "artifact_visibility",
    "enrich_artifact_records",
    "filter_artifacts",
    "compact_run_diagnostics",
]
