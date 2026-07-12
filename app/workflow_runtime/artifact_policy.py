from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any, Iterable

from app.core.paths import utc_now, write_text

# Artifact presentation is contract driven.  Runtime/UI code must never infer
# meaning from user-controlled filenames or free-form paths.
ROLE_METADATA: dict[str, dict[str, Any]] = {
    "final-report": {"visibility": "essential", "display_name": "最終報告", "display_order": 10},
    "summary": {"visibility": "essential", "display_name": "執行摘要", "display_order": 20},
    "gate": {"visibility": "essential", "display_name": "完成條件報告", "display_order": 30},
    "run-diff": {"visibility": "essential", "display_name": "變更摘要", "display_order": 40},
    "test": {"visibility": "essential", "display_name": "測試結果", "display_order": 50},
    "external-validation": {"visibility": "essential", "display_name": "外部驗證結果", "display_order": 60},
    "final-review": {"visibility": "essential", "display_name": "最終審查", "display_order": 70},
    "verifier": {"visibility": "essential", "display_name": "Verifier 證據", "display_order": 80},
    "approval": {"visibility": "supporting", "display_name": "Patch 核准紀錄", "display_order": 110},
    "step-state": {"visibility": "supporting", "display_name": "Step 狀態", "display_order": 200},
    "timeline": {"visibility": "diagnostic", "display_name": "執行時間線", "display_order": 300},
    "log": {"visibility": "diagnostic", "display_name": "完整執行記錄", "display_order": 310},
    "events": {"visibility": "diagnostic", "display_name": "事件記錄", "display_order": 320},
    "state": {"visibility": "diagnostic", "display_name": "Run 狀態", "display_order": 330},
    "trace": {"visibility": "diagnostic", "display_name": "Run Trace", "display_order": 340},
    "debug-bundle": {"visibility": "diagnostic", "display_name": "Debug Bundle", "display_order": 350},
    "version": {"visibility": "diagnostic", "display_name": "版本資訊", "display_order": 360},
    "prompt": {"visibility": "diagnostic", "display_name": "Agent Prompt", "display_order": 400},
    "step-output": {"visibility": "supporting", "display_name": "Step 輸出", "display_order": 500},
    "validation-output": {"visibility": "essential", "display_name": "驗證輸出", "display_order": 90},
    "review-feedback": {"visibility": "essential", "display_name": "Patch 審核回饋", "display_order": 165},
    "apply-result": {"visibility": "supporting", "display_name": "Patch 套用結果", "display_order": 160},
    "artifact-index": {"visibility": "diagnostic", "display_name": "Artifact Index", "display_order": 370},
    "unclassified": {"visibility": "supporting", "display_name": "未分類產物", "display_order": 900},
}

CATEGORY_METADATA: dict[str, dict[str, Any]] = {
    "validation": {"visibility": "essential", "display_name": "驗證產物", "display_order": 50},
    "report": {"visibility": "essential", "display_name": "報告產物", "display_order": 100},
    "diff": {"visibility": "essential", "display_name": "變更產物", "display_order": 120},
    "patch": {"visibility": "supporting", "display_name": "Patch 產物", "display_order": 150},
    "step": {"visibility": "supporting", "display_name": "Step 產物", "display_order": 200},
    "console": {"visibility": "diagnostic", "display_name": "Console 產物", "display_order": 300},
    "metadata": {"visibility": "diagnostic", "display_name": "Metadata 產物", "display_order": 350},
    "prompt": {"visibility": "diagnostic", "display_name": "Prompt 產物", "display_order": 400},
    "debug": {"visibility": "diagnostic", "display_name": "診斷產物", "display_order": 450},
    "unclassified": {"visibility": "supporting", "display_name": "未分類產物", "display_order": 900},
}

TEXT_APPLICATION_MEDIA_TYPES = {
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "application/toml",
    "application/sql",
    "application/javascript",
    "application/x-javascript",
    "application/x-sh",
    "application/x-shellscript",
    "image/svg+xml",
}


def artifact_visibility(_path: str = "", *, category: str | None = None, role: str | None = None) -> str:
    """Return visibility from explicit artifact metadata only.

    ``_path`` remains accepted for backward compatibility, but is deliberately
    ignored.  Filenames and paths are user/agent controlled and must never be
    used as semantic classifiers.
    """
    role_meta = ROLE_METADATA.get(str(role or "").strip())
    if role_meta:
        return str(role_meta["visibility"])
    category_meta = CATEGORY_METADATA.get(str(category or "").strip())
    if category_meta:
        return str(category_meta["visibility"])
    return "supporting"


def artifact_display_metadata(*, category: str | None = None, role: str | None = None) -> dict[str, Any]:
    category_key = str(category or "unclassified").strip() or "unclassified"
    role_key = str(role or "unclassified").strip() or "unclassified"
    category_meta = CATEGORY_METADATA.get(category_key)
    role_meta = ROLE_METADATA.get(role_key)
    fallback_category = CATEGORY_METADATA["unclassified"]
    fallback_role = ROLE_METADATA["unclassified"]
    category_effective = category_meta or fallback_category
    role_effective = role_meta or {}
    return {
        "category": category_key,
        "role": role_key,
        "visibility": role_effective.get("visibility") or category_effective.get("visibility") or "supporting",
        "display_name": role_effective.get("display_name") or category_effective.get("display_name") or fallback_role["display_name"],
        "display_order": int(role_effective.get("display_order", category_effective.get("display_order", 900))),
    }


def artifact_preview_kind(*, media_type: str | None = None, role: str | None = None) -> str:
    """Return an explicit renderer contract from file format metadata.

    This selects a renderer from MIME/role metadata only; it never inspects a
    filename or artifact content to guess meaning.
    """
    media = str(media_type or "").split(";", 1)[0].strip().lower()
    role_key = str(role or "").strip().lower()
    if media in {"application/json", "application/ld+json"} or media.endswith("+json") or role_key in {"state", "events", "debug-bundle", "version", "artifact-index"}:
        return "json"
    if media == "text/markdown":
        return "markdown"
    if role_key in {"log", "timeline"}:
        return "log"
    if media.startswith("text/") or media in TEXT_APPLICATION_MEDIA_TYPES or media.endswith("+xml") or not media:
        return "text"
    return "binary"


def enrich_artifact_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in records:
        row = dict(item)
        defaults = artifact_display_metadata(category=row.get("category"), role=row.get("role"))
        if not row.get("category"):
            row["category"] = defaults["category"]
        if not row.get("role"):
            row["role"] = defaults["role"]
        if not row.get("display_name"):
            row["display_name"] = defaults["display_name"]
        if row.get("display_order") is None:
            row["display_order"] = defaults["display_order"]
        if not row.get("visibility"):
            row["visibility"] = defaults["visibility"]
        row.setdefault("producer_step_key", None)
        if not row.get("media_type"):
            row["media_type"] = "text/plain"
        if not row.get("preview_kind"):
            row["preview_kind"] = artifact_preview_kind(media_type=row.get("media_type"), role=row.get("role"))
        enriched.append(row)
    return enriched


def filter_artifacts(records: Iterable[dict[str, Any]], view: str = "essential") -> list[dict[str, Any]]:
    rows = enrich_artifact_records(records)
    view = str(view or "essential").lower()
    if view in {"all", "debug"}:
        return rows
    if view == "diagnostic":
        return [row for row in rows if row.get("visibility") == "diagnostic"]
    if view == "supporting":
        return [row for row in rows if row.get("visibility") in {"essential", "supporting"}]
    return [row for row in rows if row.get("visibility") == "essential"]


def _diagnostic_paths(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    # These are fixed controller-owned storage roots, not semantic filename
    # guesses.  Individual artifact classification still comes from metadata.
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
            candidates.append(path)
    return sorted(set(candidates))


def compact_run_diagnostics(run: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Pack verbose diagnostics into one archive after a terminal run."""
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
        "schema": "aiwf.artifact-compaction.v2",
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
    "ROLE_METADATA",
    "CATEGORY_METADATA",
    "artifact_visibility",
    "artifact_display_metadata",
    "artifact_preview_kind",
    "enrich_artifact_records",
    "filter_artifacts",
    "compact_run_diagnostics",
]
