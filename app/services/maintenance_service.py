from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.repositories import store_repository
from app.runtime_modules.metrics import metrics


ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_input", "cancelling"}


async def cleanup_runs(keep_per_project: int = 20) -> dict[str, Any]:
    keep_per_project = max(1, min(int(keep_per_project or 20), 500))
    data = await store_repository.read()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in data.get("runs", []):
        grouped.setdefault(str(run.get("project_path") or ""), []).append(run)

    remove_ids: set[str] = set()
    remove_workspaces: list[Path] = []
    for runs in grouped.values():
        ordered = sorted(runs, key=lambda item: item.get("created_at") or "", reverse=True)
        kept_inactive = 0
        for run in ordered:
            if run.get("status") in ACTIVE_RUN_STATUSES:
                continue
            kept_inactive += 1
            if kept_inactive <= keep_per_project:
                continue
            remove_ids.add(run["id"])
            if run.get("workspace"):
                remove_workspaces.append(Path(run["workspace"]))

    if not remove_ids:
        return {"ok": True, "removedRuns": 0, "removedArtifacts": 0}

    def mutate(store):
        store["runs"] = [run for run in store.get("runs", []) if run.get("id") not in remove_ids]
        return None

    await store_repository.mutate(mutate)

    removed_artifacts = 0
    for workspace in remove_workspaces:
        try:
            resolved = workspace.resolve()
            if ".qwen-workflow" not in resolved.parts:
                continue
            if resolved.exists():
                shutil.rmtree(resolved)
                removed_artifacts += 1
        except OSError:
            continue

    metrics.increment("cleanup.runs", len(remove_ids))
    return {"ok": True, "removedRuns": len(remove_ids), "removedArtifacts": removed_artifacts}
