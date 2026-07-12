from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, Iterable


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip(" -") for line in value.splitlines() if line.strip(" -")]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_task_contract(task: dict[str, Any], *, owner: str | None = None) -> dict[str, Any]:
    """Normalize AI-authored task metadata into a small acceptance contract.

    Empty constraints remain empty; the controller does not invent file paths
    or implementation details that belong to Qwen/OpenCode.
    """
    result = dict(task)
    result["owner"] = str(result.get("owner") or owner or result.get("kind") or "build").strip().lower()
    result["acceptance"] = _string_list(result.get("acceptance") or result.get("acceptance_criteria"))
    result["scope"] = _string_list(result.get("scope") or result.get("allowed_paths"))
    result["must_change"] = _string_list(result.get("must_change") or result.get("mustChange"))
    result["must_not_change"] = _string_list(result.get("must_not_change") or result.get("mustNotChange"))
    result["validation"] = _string_list(result.get("validation") or result.get("validation_commands"))
    result["dependencies"] = _string_list(result.get("dependencies") or result.get("depends_on"))
    risk = str(result.get("risk") or "normal").strip().lower()
    result["risk"] = risk if risk in {"low", "normal", "medium", "high"} else "normal"
    result["acceptance_contract"] = {
        "scope": result["scope"],
        "must_change": result["must_change"],
        "must_not_change": result["must_not_change"],
        "validation": result["validation"],
        "acceptance": result["acceptance"],
        "dependencies": result["dependencies"],
        "risk": result["risk"],
    }
    return result


def _matches(path: str, pattern: str) -> bool:
    normalized_path = path.replace("\\", "/").lstrip("./")
    normalized_pattern = pattern.replace("\\", "/").lstrip("./")
    return (
        normalized_path == normalized_pattern
        or normalized_path.startswith(normalized_pattern.rstrip("/") + "/")
        or fnmatch(normalized_path, normalized_pattern)
    )


def validate_task_file_changes(task: dict[str, Any], changed_paths: Iterable[str]) -> list[str]:
    """Return deterministic contract violations for explicit path constraints."""
    normalized = normalize_task_contract(task)
    changed = [str(path).replace("\\", "/") for path in changed_paths]
    violations: list[str] = []
    scope = normalized.get("scope") or []
    if scope:
        outside = [path for path in changed if not any(_matches(path, pattern) for pattern in scope)]
        if outside:
            violations.append("changed file(s) outside task scope: " + ", ".join(outside))
    blocked = [path for path in changed if any(_matches(path, pattern) for pattern in normalized.get("must_not_change") or [])]
    if blocked:
        violations.append("changed protected task path(s): " + ", ".join(blocked))
    missing = [pattern for pattern in normalized.get("must_change") or [] if not any(_matches(path, pattern) for path in changed)]
    if missing:
        violations.append("required task path(s) were not changed: " + ", ".join(missing))
    return violations


__all__ = ["normalize_task_contract", "validate_task_file_changes"]
