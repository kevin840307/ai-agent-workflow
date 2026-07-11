from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DOC_NAMES = {"readme.md", "changelog.md", "contributing.md", "example.py", "examples.py", "demo.py"}


def _requested_paths(requirement: str) -> set[str]:
    matches = re.findall(r"(?:[A-Za-z]:[\\/][^\s`'\"]+|(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]+)", requirement or "")
    return {Path(match.replace("\\", "/")).name.lower() for match in matches}


def analyze_scope_delta(
    requirement: str,
    *,
    file_changes: list[dict[str, Any] | str] | None = None,
    planned_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    requested = _requested_paths(requirement)
    text = str(requirement or "").lower()
    produced: list[str] = []
    for change in file_changes or []:
        path = change if isinstance(change, str) else change.get("path") or change.get("file")
        if path:
            produced.append(str(path).replace("\\", "/"))
    expansions: list[dict[str, str]] = []
    asks_docs = any(token in text for token in ("readme", "document", "documentation", "文件", "說明"))
    asks_example = any(token in text for token in ("example", "demo", "範例", "示例"))
    asks_tests = any(token in text for token in ("test", "pytest", "測試"))
    for path in produced:
        name = Path(path).name.lower()
        if name in DOC_NAMES and name not in requested:
            if name.startswith(("readme", "changelog", "contributing")) and not asks_docs:
                expansions.append({"path": path, "kind": "unrequested_documentation", "severity": "low"})
            elif name in {"example.py", "examples.py", "demo.py"} and not asks_example:
                expansions.append({"path": path, "kind": "unrequested_example", "severity": "low"})
        if (name.startswith("test_") or "/tests/" in f"/{path.lower()}/") and not asks_tests:
            # Tests are normally required by the platform, so this is only informational.
            expansions.append({"path": path, "kind": "platform_validation_artifact", "severity": "info"})
    task_count = len(planned_tasks or [])
    if task_count > 5 and len(text) < 300:
        expansions.append({"path": "task-manifest", "kind": "over_planned", "severity": "medium"})
    meaningful = [item for item in expansions if item["severity"] not in {"info"}]
    status = "warning" if meaningful else "pass"
    return {
        "schema": "aiwf.scope-delta.v1",
        "status": status,
        "requested_paths": sorted(requested),
        "produced_paths": produced,
        "expansions": expansions,
        "unrequested_count": len(meaningful),
        "recommendation": "Remove or ask approval for unrelated output." if meaningful else "Produced scope matches the request and platform validation needs.",
    }


__all__ = ["analyze_scope_delta"]
