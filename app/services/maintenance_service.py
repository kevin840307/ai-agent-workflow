from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.persistence.repositories import store as store_repository
from app.core.metrics import metrics
from app.security.workspace_guard import PROJECT_WORKFLOW_DIR, LEGACY_WORKFLOW_DIR


ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_input", "cancelling"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_project_key(run: dict[str, Any]) -> str:
    return str(run.get("original_project_path") or run.get("project_path") or "")


def _workspace_is_safe_to_remove(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return PROJECT_WORKFLOW_DIR in resolved.parts or LEGACY_WORKFLOW_DIR in resolved.parts


def _candidate_orphan_workspaces(data: dict[str, Any]) -> list[Path]:
    known = {str(Path(run.get("workspace") or "").resolve()) for run in data.get("runs", []) if run.get("workspace")}
    roots: set[Path] = set()
    for run in data.get("runs", []):
        for key in ["original_project_path", "project_path"]:
            raw = run.get(key)
            if raw:
                roots.add(Path(raw) / PROJECT_WORKFLOW_DIR / "runs")
                roots.add(Path(raw) / LEGACY_WORKFLOW_DIR / "runs")
    orphans: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for run_dir in root.glob("session-*/run-*"):
            try:
                marker = str(run_dir.resolve())
            except OSError:
                continue
            if marker not in known:
                orphans.append(run_dir)
    return orphans


async def cleanup_runs(
    keep_per_project: int = 20,
    *,
    older_than_days: int | None = None,
    dry_run: bool = False,
    include_orphan_workspaces: bool = False,
) -> dict[str, Any]:
    """Apply run/artifact retention without touching active runs.

    Retention is intentionally conservative:
    - active runs are never removed;
    - the newest N inactive runs per project are always kept;
    - older_than_days is an additional selector, not a reason to delete newer
      records that are within the keep budget;
    - workspace deletion is limited to known workflow run directories.
    """
    keep_per_project = max(1, min(int(keep_per_project or 20), 500))
    older_than_days = int(older_than_days) if older_than_days is not None else None
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days) if older_than_days and older_than_days > 0 else None
    data = await store_repository.read()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in data.get("runs", []):
        grouped.setdefault(_run_project_key(run), []).append(run)

    remove_ids: set[str] = set()
    remove_workspaces: list[Path] = []
    kept_counts: dict[str, int] = {}
    for project_key, runs in grouped.items():
        ordered = sorted(runs, key=lambda item: item.get("created_at") or item.get("updated_at") or "", reverse=True)
        kept_inactive = 0
        for run in ordered:
            if run.get("status") in ACTIVE_RUN_STATUSES:
                continue
            kept_inactive += 1
            if kept_inactive <= keep_per_project:
                continue
            if cutoff is not None:
                run_time = _parse_dt(run.get("ended_at") or run.get("updated_at") or run.get("created_at"))
                if run_time is not None and run_time > cutoff:
                    continue
            remove_ids.add(run["id"])
            if run.get("workspace"):
                remove_workspaces.append(Path(run["workspace"]))
        kept_counts[project_key] = kept_inactive - len([run_id for run_id in remove_ids if any(r.get("id") == run_id for r in runs)])

    orphan_workspaces = _candidate_orphan_workspaces(data) if include_orphan_workspaces else []
    removable_workspaces = [path for path in [*remove_workspaces, *orphan_workspaces] if _workspace_is_safe_to_remove(path)]

    result = {
        "schema": "aiwf.artifact-retention.v1",
        "ok": True,
        "dryRun": bool(dry_run),
        "keepPerProject": keep_per_project,
        "olderThanDays": older_than_days,
        "removedRuns": len(remove_ids),
        "removedArtifacts": len(removable_workspaces),
        "candidateRunIds": sorted(remove_ids),
        "candidateWorkspaces": [str(path) for path in removable_workspaces],
        "orphanWorkspaceCount": len(orphan_workspaces),
    }
    if dry_run:
        return result

    if remove_ids:
        def mutate(store):
            store["runs"] = [run for run in store.get("runs", []) if run.get("id") not in remove_ids]
            return None

        await store_repository.mutate(mutate)

    actually_removed_artifacts = 0
    for workspace in removable_workspaces:
        try:
            if workspace.exists():
                shutil.rmtree(workspace)
                actually_removed_artifacts += 1
        except OSError:
            continue

    metrics.increment("cleanup.runs", len(remove_ids))
    result["removedArtifacts"] = actually_removed_artifacts
    return result
