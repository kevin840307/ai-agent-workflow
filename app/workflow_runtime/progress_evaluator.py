from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.runtime_modules.files import project_file_snapshot


def _count_status(items: list[dict[str, Any]], status: str) -> int:
    return sum(1 for item in items if str(item.get("status") or "") == status)


def capture_progress(run: dict[str, Any], project_path: str | Path | None = None) -> dict[str, Any]:
    """Capture cheap monotonic signals used to decide whether repair is helping."""
    files: list[tuple[str, int, int]] = []
    if project_path:
        try:
            snapshot = project_file_snapshot(Path(project_path).expanduser().resolve())
            files = sorted((path, int(meta[0]), int(meta[1])) for path, meta in snapshot.items())
        except (OSError, ValueError):
            files = []
    validations = [item for item in (run.get("validation_results") or []) if isinstance(item, dict)]
    latest = validations[-1] if validations else {}
    tasks = [item for item in (run.get("tasks") or []) if isinstance(item, dict)]
    acceptance = [item for item in (run.get("task_acceptance") or []) if isinstance(item, dict)]
    scope_delta = run.get("scope_delta") if isinstance(run.get("scope_delta"), dict) else {}
    file_digest = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {
        "schema": "aiwf.progress-snapshot.v2",
        "file_digest": file_digest,
        "file_count": len(files),
        "changed_file_count": len(set(str(item) for item in (run.get("changed_files") or []))),
        "tasks_passed": _count_status(tasks, "passed") + _count_status(tasks, "done"),
        "tasks_failed": _count_status(tasks, "failed"),
        "acceptance_passed": _count_status(acceptance, "passed"),
        "required_failures": int(latest.get("required_failures") or 0),
        "validation_passed": sum(1 for item in validations if item.get("status") in {"passed", "passed_with_baseline"}),
        "scope_violations": len(scope_delta.get("violations") or []),
        "checkpoint": str(run.get("last_task_checkpoint_id") or run.get("last_checkpoint_id") or ""),
    }


def compare_progress(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"state": "initial", "improved": False, "regressed": False, "reasons": []}
    reasons: list[str] = []
    regressions: list[str] = []
    lower_is_better = ("required_failures", "tasks_failed", "scope_violations")
    higher_is_better = ("tasks_passed", "acceptance_passed", "validation_passed", "changed_file_count")
    for key in lower_is_better:
        before, after = int(previous.get(key) or 0), int(current.get(key) or 0)
        if after < before:
            reasons.append(f"{key}:{before}->{after}")
        elif after > before:
            regressions.append(f"{key}:{before}->{after}")
    for key in higher_is_better:
        before, after = int(previous.get(key) or 0), int(current.get(key) or 0)
        if after > before:
            reasons.append(f"{key}:{before}->{after}")
        elif after < before and key not in {"changed_file_count"}:
            regressions.append(f"{key}:{before}->{after}")
    if previous.get("checkpoint") != current.get("checkpoint") and current.get("checkpoint"):
        reasons.append("checkpoint advanced")
    if previous.get("file_digest") != current.get("file_digest") and not regressions:
        reasons.append("candidate files changed")
    improved = bool(reasons) and not regressions
    regressed = bool(regressions) and not reasons
    return {
        "state": "improved" if improved else "regressed" if regressed else "changed" if (reasons or regressions) else "unchanged",
        "improved": improved,
        "regressed": regressed,
        "reasons": reasons,
        "regressions": regressions,
    }


def progress_signature(snapshot_or_run: dict[str, Any], project_path: str | Path | None = None) -> str:
    snapshot = snapshot_or_run if snapshot_or_run.get("schema") == "aiwf.progress-snapshot.v2" else capture_progress(snapshot_or_run, project_path)
    raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


__all__ = ["capture_progress", "compare_progress", "progress_signature"]
