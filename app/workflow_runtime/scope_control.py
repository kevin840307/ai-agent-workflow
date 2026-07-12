from __future__ import annotations

from typing import Any


def analyze_scope_delta(
    requirement: str,
    *,
    file_changes: list[dict[str, Any] | str] | None = None,
    planned_tasks: list[dict[str, Any]] | None = None,
    requested_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Compare explicit task-contract paths; never infer scope from prose."""
    declared = {str(item).replace("\\", "/").lstrip("./") for item in requested_paths or [] if str(item).strip()}
    for task in planned_tasks or []:
        if not isinstance(task, dict):
            continue
        for field in ("expected_files", "expectedFiles", "allowed_write_paths", "allowedWritePaths"):
            for item in task.get(field) or []:
                value = str(item).replace("\\", "/").lstrip("./")
                if value:
                    declared.add(value)
    produced: list[str] = []
    for change in file_changes or []:
        path = change if isinstance(change, str) else change.get("path") or change.get("file")
        if path:
            produced.append(str(path).replace("\\", "/").lstrip("./"))
    expansions = []
    if declared:
        for path in produced:
            covered = path in declared or any(item.endswith("/") and path.startswith(item) for item in declared)
            if not covered:
                expansions.append({"path": path, "kind": "outside_declared_contract", "severity": "medium"})
    status = "warning" if expansions else "pass"
    return {
        "schema": "aiwf.scope-delta.v2",
        "status": status,
        "source": "explicit_contract" if declared else "no_declared_scope",
        "requested_paths": sorted(declared),
        "produced_paths": produced,
        "expansions": expansions,
        "unrequested_count": len(expansions),
        "recommendation": "Review files outside the explicit task contract." if expansions else "Produced files comply with the explicit task contract or no path restriction was declared.",
    }


__all__ = ["analyze_scope_delta"]
