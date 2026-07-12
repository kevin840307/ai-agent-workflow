from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

from app.core.paths import utc_now, write_text
from app.security.isolated_workspace import file_sha256

JOURNAL_SCHEMA = "aiwf.atomic-delivery-transaction.v2"
TERMINAL_STATUSES = {"committed", "rolled_back"}


class DeliveryJournalError(RuntimeError):
    pass


def _safe_relative(value: str | Path) -> Path:
    rel = Path(value)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise DeliveryJournalError(f"Unsafe relative path: {value}")
    return rel


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".aiwf.tmp", dir=str(target.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def persist_delivery_journal(path: Path, journal: dict[str, Any]) -> None:
    journal["updated_at"] = utc_now()
    write_text(path, json.dumps(journal, indent=2, ensure_ascii=False) + "\n")


def load_delivery_journal(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("schema") == JOURNAL_SCHEMA else None


def transaction_id_for(run_id: str, changed_files: Iterable[str]) -> str:
    normalized = sorted({_safe_relative(item).as_posix() for item in changed_files})
    raw = f"{run_id}|" + "|".join(normalized)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def prepare_delivery_journal(
    original_dir: Path,
    isolated_dir: Path,
    changed_files: Iterable[str],
    *,
    baseline_hashes: dict[str, str | None] | None,
    backup_dir: Path,
    transaction_id: str,
    run_id: str,
    fencing_token: int | None = None,
    journal_path: Path | None = None,
) -> dict[str, Any]:
    """Prepare all rollback evidence before the first project mutation.

    A crash during PREPARING is harmless because no original file is changed.
    The next invocation removes the incomplete backup directory and prepares a
    fresh journal. Once PREPARED is persisted, that operation list is the only
    authority for resume/rollback; the diff is never recomputed mid-transaction.
    """
    original = Path(original_dir).expanduser().resolve()
    isolated = Path(isolated_dir).expanduser().resolve()
    selected = sorted({_safe_relative(item).as_posix() for item in changed_files})
    baseline = baseline_hashes or {}
    conflicts: list[dict[str, Any]] = []
    for rel_text in selected:
        current = file_sha256(original / rel_text)
        expected = baseline.get(rel_text)
        if baseline_hashes is not None and current != expected:
            conflicts.append({"path": rel_text, "expected_sha256": expected, "current_sha256": current})
    if conflicts:
        raise DeliveryJournalError("ATOMIC_APPLY_CONFLICT: " + json.dumps(conflicts, ensure_ascii=False))

    shutil.rmtree(backup_dir, ignore_errors=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    operations: list[dict[str, Any]] = []
    for position, rel_text in enumerate(selected):
        rel = _safe_relative(rel_text)
        source = (isolated / rel).resolve()
        target = (original / rel).resolve()
        source.relative_to(isolated)
        target.relative_to(original)
        target_before_sha = file_sha256(target)
        existed = target.is_file()
        backup = backup_dir / rel
        if existed:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        action = "write" if source.is_file() else "delete"
        operations.append(
            {
                "position": position,
                "path": rel_text,
                "action": action,
                "status": "prepared",
                "existed": existed,
                "backup": str(backup) if existed else None,
                "target_before_sha256": target_before_sha,
                "source_sha256": file_sha256(source) if action == "write" else None,
                "prepared_at": utc_now(),
            }
        )
    journal = {
        "schema": JOURNAL_SCHEMA,
        "transaction_id": transaction_id,
        "run_id": run_id,
        "status": "prepared",
        "fencing_token": fencing_token,
        "original_project_path": str(original),
        "isolated_project_path": str(isolated),
        "backup_dir": str(backup_dir.resolve()),
        "changed_files": selected,
        "operations": operations,
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    return journal


def _operation_is_applied(original: Path, operation: dict[str, Any]) -> bool:
    target = original / _safe_relative(str(operation.get("path") or ""))
    if operation.get("action") == "delete":
        return not target.exists()
    return target.is_file() and file_sha256(target) == operation.get("source_sha256")


def _operation_is_baseline(original: Path, operation: dict[str, Any]) -> bool:
    target = original / _safe_relative(str(operation.get("path") or ""))
    if operation.get("existed"):
        return target.is_file() and file_sha256(target) == operation.get("target_before_sha256")
    return not target.exists()


def apply_delivery_journal(
    journal: dict[str, Any],
    *,
    journal_path: Path | None = None,
    on_persist: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    original = Path(str(journal["original_project_path"])).expanduser().resolve()
    isolated = Path(str(journal["isolated_project_path"])).expanduser().resolve()
    if journal.get("status") in TERMINAL_STATUSES:
        return journal
    journal["status"] = "applying"
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    if on_persist:
        on_persist(journal)

    for operation in journal.get("operations") or []:
        rel = _safe_relative(str(operation.get("path") or ""))
        target = (original / rel).resolve()
        source = (isolated / rel).resolve()
        target.relative_to(original)
        source.relative_to(isolated)
        if _operation_is_applied(original, operation):
            operation["status"] = "applied"
            operation.setdefault("applied_at", utc_now())
        else:
            if not _operation_is_baseline(original, operation):
                raise DeliveryJournalError(
                    "ATOMIC_APPLY_CONFLICT_DURING_RESUME: "
                    + json.dumps(
                        {
                            "path": operation.get("path"),
                            "expected_sha256": operation.get("target_before_sha256"),
                            "current_sha256": file_sha256(target),
                        },
                        ensure_ascii=False,
                    )
                )
            if operation.get("action") == "write":
                if not source.is_file() or file_sha256(source) != operation.get("source_sha256"):
                    raise DeliveryJournalError(f"ATOMIC_SOURCE_CHANGED: {operation.get('path')}")
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy(source, target)
            elif target.exists():
                if target.is_dir():
                    raise DeliveryJournalError(f"ATOMIC_TARGET_IS_DIRECTORY: {operation.get('path')}")
                target.unlink()
            operation["status"] = "applied"
            operation["applied_at"] = utc_now()
        if journal_path:
            persist_delivery_journal(journal_path, journal)
        if on_persist:
            on_persist(journal)

    journal["status"] = "verifying"
    journal["applied_at"] = utc_now()
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    if on_persist:
        on_persist(journal)
    return journal


def rollback_delivery_journal(
    journal: dict[str, Any],
    *,
    journal_path: Path | None = None,
    on_persist: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    original = Path(str(journal["original_project_path"])).expanduser().resolve()
    journal["status"] = "rolling_back"
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    if on_persist:
        on_persist(journal)

    restored: list[str] = []
    removed: list[str] = []
    for operation in reversed(list(journal.get("operations") or [])):
        rel = _safe_relative(str(operation.get("path") or ""))
        target = (original / rel).resolve()
        target.relative_to(original)
        # A crash may happen after os.replace/unlink but before the operation
        # status is persisted, so inspect the actual target state as well.
        was_applied = operation.get("status") in {"applied", "rolled_back"} or _operation_is_applied(original, operation)
        if operation.get("status") == "rolled_back":
            continue
        if not was_applied and _operation_is_baseline(original, operation):
            operation["status"] = "rolled_back"
            operation["rolled_back_at"] = utc_now()
        elif operation.get("existed"):
            backup = Path(str(operation.get("backup") or ""))
            if not backup.is_file() or file_sha256(backup) != operation.get("target_before_sha256"):
                raise DeliveryJournalError(f"ATOMIC_BACKUP_MISSING_OR_CHANGED: {operation.get('path')}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_copy(backup, target)
            restored.append(str(target))
            operation["status"] = "rolled_back"
            operation["rolled_back_at"] = utc_now()
        else:
            if target.exists():
                if target.is_dir():
                    raise DeliveryJournalError(f"ATOMIC_ROLLBACK_TARGET_IS_DIRECTORY: {operation.get('path')}")
                target.unlink()
                removed.append(str(target))
            operation["status"] = "rolled_back"
            operation["rolled_back_at"] = utc_now()
        if journal_path:
            persist_delivery_journal(journal_path, journal)
        if on_persist:
            on_persist(journal)

    journal["status"] = "rolled_back"
    journal["rolled_back_at"] = utc_now()
    journal["rollback"] = {
        "schema": "aiwf.atomic-rollback.v2",
        "restored_files": restored,
        "removed_files": removed,
    }
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    if on_persist:
        on_persist(journal)
    return journal


def commit_delivery_journal(
    journal: dict[str, Any],
    *,
    verification: dict[str, Any],
    journal_path: Path | None = None,
    on_persist: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    journal["status"] = "committed"
    journal["verification"] = verification
    journal["committed_at"] = utc_now()
    for operation in journal.get("operations") or []:
        if operation.get("status") == "applied":
            operation["status"] = "committed"
    if journal_path:
        persist_delivery_journal(journal_path, journal)
    if on_persist:
        on_persist(journal)
    return journal


def journal_summary(journal: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": journal.get("schema") or JOURNAL_SCHEMA,
        "transaction_id": journal.get("transaction_id"),
        "run_id": journal.get("run_id"),
        "status": journal.get("status"),
        "fencing_token": journal.get("fencing_token"),
        "changed_files": list(journal.get("changed_files") or []),
        "backup_dir": journal.get("backup_dir"),
        "operations": [dict(item) for item in journal.get("operations") or []],
        "created_at": journal.get("created_at"),
        "updated_at": journal.get("updated_at"),
        "applied_at": journal.get("applied_at"),
        "committed_at": journal.get("committed_at"),
        "rolled_back_at": journal.get("rolled_back_at"),
        "rollback": journal.get("rollback"),
    }


__all__ = [
    "DeliveryJournalError",
    "JOURNAL_SCHEMA",
    "apply_delivery_journal",
    "commit_delivery_journal",
    "journal_summary",
    "load_delivery_journal",
    "persist_delivery_journal",
    "prepare_delivery_journal",
    "rollback_delivery_journal",
    "transaction_id_for",
]
