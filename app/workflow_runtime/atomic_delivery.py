from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.paths import utc_now, write_text
from app.runtime_modules.errors import WorkflowError
from app.security.isolated_workspace import changed_project_files
from app.workflow_runtime.autopilot_policy import evaluate_delivery_validation
from app.workflow_runtime.delivery_journal import (
    DeliveryJournalError,
    apply_delivery_journal,
    commit_delivery_journal,
    journal_summary,
    load_delivery_journal,
    prepare_delivery_journal,
    rollback_delivery_journal,
    transaction_id_for,
)
from app.workflow_runtime.run_lease import RunLeaseConflict, assert_run_lease
from app.workflow_runtime.validators import execute_validation_plan


def _transaction_for_run(journal: dict[str, Any]) -> dict[str, Any]:
    summary = journal_summary(journal)
    transaction_status = str(summary.get("status") or "")
    # Keep the previous public terminal label for API/UI compatibility while
    # exposing the real write-ahead transaction state explicitly.
    if transaction_status == "committed":
        summary["status"] = "applied"
    summary["transaction_status"] = transaction_status
    return summary


def _assert_delivery_lease(run: dict[str, Any], expected_token: int | None) -> None:
    lease = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else None
    if not lease:
        return
    owner_id = str(lease.get("owner_id") or "")
    token = int(expected_token if expected_token is not None else lease.get("fencing_token") or 0)
    assert_run_lease(run, owner_id=owner_id, fencing_token=token)


async def deliver_isolated_changes(
    run: dict[str, Any],
    *,
    update_run: Callable[[str, Callable[[dict[str, Any]], Any]], Awaitable[dict[str, Any]]],
    log: Callable[[dict[str, Any], str], Awaitable[None]],
) -> dict[str, Any] | None:
    """Deliver only Agent-produced files through a crash-recoverable journal."""
    if str(run.get("patch_mode") or "") != "atomic_apply":
        return None
    existing_delivery = run.get("atomic_delivery") if isinstance(run.get("atomic_delivery"), dict) else None
    if existing_delivery and existing_delivery.get("status") == "applied":
        return existing_delivery
    original_raw = run.get("original_project_path")
    isolated_raw = run.get("isolated_project_path") or run.get("project_path")
    if not original_raw or not isolated_raw:
        return None
    original = Path(str(original_raw)).expanduser().resolve()
    isolated = Path(str(isolated_raw)).expanduser().resolve()
    if original == isolated:
        return None

    workspace = Path(str(run.get("workspace") or ".")).expanduser().resolve()
    workflow_dir = workspace / ".workflow"
    output = workspace / "output"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    journal_path = workflow_dir / "atomic-delivery-transaction.json"
    backup_dir = workflow_dir / "atomic-backup"
    journal = load_delivery_journal(journal_path)

    if journal and journal.get("run_id") != str(run.get("id")):
        raise WorkflowError("ATOMIC_JOURNAL_RUN_MISMATCH: existing delivery journal belongs to another Run")
    changed = list(journal.get("changed_files") or []) if journal else changed_project_files(original, isolated)
    if not changed:
        evidence = {
            "schema": "aiwf.atomic-delivery.v3",
            "status": "no_changes",
            "changed_files": [],
            "completed_at": utc_now(),
        }
        write_text(output / "atomic-delivery.json", json.dumps(evidence, indent=2, ensure_ascii=False))
        return evidence

    transaction_id = transaction_id_for(str(run.get("id") or ""), changed)
    if journal and journal.get("transaction_id") != transaction_id:
        raise WorkflowError("ATOMIC_JOURNAL_DIFF_MISMATCH: the prepared operation list no longer matches this Run")
    lease = run.get("run_lease") if isinstance(run.get("run_lease"), dict) else {}
    fencing_token = int(lease.get("fencing_token") or 0) or None

    async def persist_journal_state(current: dict[str, Any]) -> None:
        transaction = _transaction_for_run(current)

        def apply(item: dict[str, Any]) -> None:
            _assert_delivery_lease(item, fencing_token)
            item["atomic_delivery_transaction"] = transaction
            item["updated_at"] = utc_now()

        latest = await update_run(str(run["id"]), apply)
        if latest:
            run.update(latest)

    try:
        _assert_delivery_lease(run, fencing_token)
        if not journal or journal.get("status") in {"preparing"}:
            await log(run, f"autopilot: preparing rollback evidence for {len(changed)} file change(s)")
            journal = prepare_delivery_journal(
                original,
                isolated,
                changed,
                baseline_hashes=dict(run.get("original_project_hashes") or {}),
                backup_dir=backup_dir,
                transaction_id=transaction_id,
                run_id=str(run.get("id") or ""),
                fencing_token=fencing_token,
                journal_path=journal_path,
            )
            await persist_journal_state(journal)
        if journal.get("status") == "committed":
            existing = run.get("atomic_delivery") if isinstance(run.get("atomic_delivery"), dict) else None
            return existing or {
                "schema": "aiwf.atomic-delivery.v3",
                "status": "applied",
                "changed_files": changed,
                "transaction": _transaction_for_run(journal),
                "completed_at": journal.get("committed_at") or utc_now(),
            }
        if journal.get("status") == "rolled_back":
            raise WorkflowError("ATOMIC_DELIVERY_ALREADY_ROLLED_BACK: start a new Run before applying again")

        await log(run, f"autopilot: applying {len(changed)} prepared file operation(s)")
        journal = apply_delivery_journal(journal, journal_path=journal_path)
        await persist_journal_state(journal)
    except (DeliveryJournalError, RunLeaseConflict) as exc:
        raise WorkflowError(f"ATOMIC_APPLY_FAILED: {exc}") from exc

    profile = run.get("project_validation_profile") if isinstance(run.get("project_validation_profile"), dict) else None
    categories = set((profile or {}).get("fast_categories") or []) or None
    timeout = max(30, min(int(os.environ.get("AIWF_ATOMIC_VERIFY_TIMEOUT_SEC", "600") or 600), 86400))
    verification = await execute_validation_plan(
        original,
        timeout_sec=timeout,
        categories=categories,
        fail_fast=False,
        profile=profile,
        baseline_result=run.get("baseline_validation") if isinstance(run.get("baseline_validation"), dict) else None,
    )
    policy = evaluate_delivery_validation(run, verification)
    accepted = bool(policy.get("allowed"))
    evidence = {
        "schema": "aiwf.atomic-delivery.v3",
        "status": "applied" if accepted else "rolled_back",
        "changed_files": changed,
        "transaction": _transaction_for_run(journal),
        "post_apply_validation": verification,
        "delivery_policy": policy,
        "completed_at": utc_now(),
    }
    if not accepted:
        try:
            journal = rollback_delivery_journal(journal, journal_path=journal_path)
            await persist_journal_state(journal)
        except (DeliveryJournalError, RunLeaseConflict) as exc:
            evidence["rollback_error"] = str(exc)
            write_text(output / "atomic-delivery.json", json.dumps(evidence, indent=2, ensure_ascii=False))
            raise WorkflowError(f"ATOMIC_ROLLBACK_FAILED: {exc}") from exc
        evidence["transaction"] = _transaction_for_run(journal)
        evidence["rollback"] = journal.get("rollback")
        write_text(output / "atomic-delivery.json", json.dumps(evidence, indent=2, ensure_ascii=False))
        raise WorkflowError(
            "ATOMIC_POST_APPLY_VALIDATION_FAILED: original project was restored; "
            + "; ".join(policy.get("errors") or ["validation policy rejected delivery"])
        )

    try:
        _assert_delivery_lease(run, fencing_token)
        journal = commit_delivery_journal(journal, verification=verification, journal_path=journal_path)
        await persist_journal_state(journal)
    except (DeliveryJournalError, RunLeaseConflict) as exc:
        # A lost lease must never be allowed to commit. Restore from the already
        # prepared evidence so another controller starts from a clean project.
        journal = rollback_delivery_journal(journal, journal_path=journal_path)
        await persist_journal_state(journal)
        raise WorkflowError(f"ATOMIC_COMMIT_FENCED: {exc}") from exc

    evidence["transaction"] = _transaction_for_run(journal)

    def persist(item: dict[str, Any]) -> None:
        _assert_delivery_lease(item, fencing_token)
        item["patch_status"] = "applied"
        item["atomic_delivery"] = evidence
        item["delivered_project_path"] = str(original)
        item["changed_files"] = list(changed)
        item["atomic_delivery_transaction"] = _transaction_for_run(journal)
        item["updated_at"] = utc_now()

    latest = await update_run(str(run["id"]), persist)
    if latest:
        run.update(latest)
    write_text(output / "atomic-delivery.json", json.dumps(evidence, indent=2, ensure_ascii=False))
    await log(run, "autopilot: crash-safe delivery and required post-apply validation passed")
    return evidence


__all__ = ["deliver_isolated_changes"]
