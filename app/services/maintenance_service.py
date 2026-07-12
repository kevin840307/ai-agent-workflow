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

async def inspect_runtime_invariants(*, repair: bool = False) -> dict[str, Any]:
    """Inspect and optionally repair durable controller invariants.

    Repairs are intentionally limited to states that are provably stale:
    expired leases, terminal-run locks, orphan managed processes, and unfinished
    delivery journals whose owning Run no longer has a live execution task.
    """
    from app.runtime_modules import api as runtime
    from app.workflow_runtime.delivery_journal import load_delivery_journal, rollback_delivery_journal
    from app.workflow_runtime.run_lease import lease_is_expired, release_run_lease
    from app.workflow_runtime.run_lifecycle import clear_project_lock
    from app.core.paths import utc_now

    data = await store_repository.read()
    issues: list[dict[str, Any]] = []
    repaired: list[dict[str, Any]] = []
    active_statuses = ACTIVE_RUN_STATUSES
    task_ids = {str(key) for key, task in runtime.running_tasks.items() if task and not task.done()}
    process_run_ids = set()
    values = runtime.running_processes.values() if hasattr(runtime.running_processes, "values") else []
    for process in values:
        run_id = getattr(process, "run_id", None) or getattr(process, "aiwf_run_id", None)
        if run_id:
            process_run_ids.add(str(run_id))

    changed = False
    for run in data.get("runs", []):
        run_id = str(run.get("id") or "")
        status = str(run.get("status") or "")
        lease = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
        workspace = Path(str(run.get("workspace") or "")) if run.get("workspace") else None
        journal_path = workspace / ".workflow" / "atomic-delivery-transaction.json" if workspace else None
        journal = load_delivery_journal(journal_path) if journal_path else None

        if status not in active_statuses and lease:
            issue = {"run_id": run_id, "code": "TERMINAL_RUN_HAS_LEASE", "status": status}
            issues.append(issue)
            if repair and release_run_lease(run):
                repaired.append(issue)
                changed = True
        elif status in active_statuses and lease and lease_is_expired(lease):
            issue = {"run_id": run_id, "code": "ACTIVE_RUN_LEASE_EXPIRED", "status": status}
            issues.append(issue)
            live_task = run_id in task_ids
            if repair and not live_task:
                if journal and journal.get("status") not in {"committed", "rolled_back"}:
                    try:
                        rollback_delivery_journal(journal, journal_path=journal_path)
                        run["atomic_delivery_transaction"] = {"status": "rolled_back", "recovered_by": "invariant_monitor"}
                    except Exception as exc:
                        issue["rollback_error"] = str(exc)[:1000]
                release_run_lease(run)
                clear_project_lock(run)
                run["project_lock"] = None
                run["status"] = "failed"
                run["error_code"] = "RUN_LEASE_EXPIRED"
                run["error"] = "Run lease expired without a live controller task; state was safely recovered."
                run["restart_recoverable"] = True
                run["updated_at"] = utc_now()
                repaired.append(issue)
                changed = True
        if status in active_statuses and run_id not in task_ids and run_id not in process_run_ids and not lease:
            issues.append({"run_id": run_id, "code": "ACTIVE_RUN_WITHOUT_EXECUTION_OWNER", "status": status})
        if journal and journal.get("status") not in {"committed", "rolled_back"} and status not in active_statuses:
            issue = {"run_id": run_id, "code": "STALE_DELIVERY_TRANSACTION", "transaction_status": journal.get("status")}
            issues.append(issue)
            if repair:
                try:
                    rolled = rollback_delivery_journal(journal, journal_path=journal_path)
                    run["atomic_delivery_transaction"] = {"status": rolled.get("status"), "recovered_by": "invariant_monitor"}
                    repaired.append(issue)
                    changed = True
                except Exception as exc:
                    issue["rollback_error"] = str(exc)[:1000]

    if repair and changed:
        await store_repository.mutate(lambda store: store.update(data))
    orphan_result = None
    if repair:
        reaper = getattr(runtime.running_processes, "reap_orphans", None)
        if callable(reaper):
            orphan_result = await __import__("asyncio").to_thread(reaper)
    return {
        "schema": "aiwf.runtime-invariants.v1",
        "status": "pass" if not issues else ("repaired" if repair and repaired else "warning"),
        "issue_count": len(issues),
        "repaired_count": len(repaired),
        "issues": issues,
        "repaired": repaired,
        "active_task_count": len(task_ids),
        "active_process_run_count": len(process_run_ids),
        "orphan_reaper": orphan_result,
    }


async def runtime_invariant_monitor(stop_event: Any, *, interval_seconds: int = 60) -> None:
    import asyncio
    interval = max(10, int(interval_seconds or 60))
    while not stop_event.is_set():
        try:
            await inspect_runtime_invariants(repair=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            metrics.increment("invariants.monitor_errors")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
