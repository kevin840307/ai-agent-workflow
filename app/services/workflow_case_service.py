from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASE_DIRS = [ROOT / "tests" / "workflow_cases", ROOT / "data" / "workflow-cases"]


def _case_roots() -> list[Path]:
    return [path for path in DEFAULT_CASE_DIRS if path.exists()]


def list_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in _case_roots():
        for path in sorted(root.iterdir()):
            if not path.is_dir() or not (path / "requirement.md").exists():
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            expected_path = path / "expected_behavior.json"
            expected = {}
            if expected_path.exists():
                expected = json.loads(expected_path.read_text(encoding="utf-8"))
            cases.append({
                "id": path.name,
                "name": path.name.replace("-", " ").title(),
                "path": str(path),
                "workflow": expected.get("workflow") or "adaptive-auto-workflow",
                "has_validation": (path / "validation.py").exists(),
                "expected": expected,
                "requirement_preview": (path / "requirement.md").read_text(encoding="utf-8")[:400],
            })
    return cases


def get_case(case_id: str) -> dict[str, Any]:
    for case in list_cases():
        if case["id"] == case_id:
            path = Path(case["path"])
            case = dict(case)
            case["requirement"] = (path / "requirement.md").read_text(encoding="utf-8")
            if (path / "validation.py").exists():
                case["validation_script"] = (path / "validation.py").read_text(encoding="utf-8")
            return case
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="workflow case not found")
