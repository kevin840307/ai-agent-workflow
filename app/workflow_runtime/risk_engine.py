from __future__ import annotations

from pathlib import Path
from typing import Any

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _level(score: int) -> str:
    if score >= 10:
        return "critical"
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def assess_risk(
    requirement: str,
    *,
    project_path: str | Path | None = None,
    expected_files: list[str] | None = None,
    estimated_file_count: int | None = None,
    risk_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess explicit contract declarations and structural change size only."""
    metadata = dict(risk_metadata or {})
    explicit_level = str(metadata.get("level") or "").strip().lower()
    if explicit_level and explicit_level not in RISK_ORDER:
        raise ValueError(f"Unsupported risk level: {explicit_level}")
    reasons = [str(item) for item in metadata.get("reasons") or [] if str(item).strip()]
    score = int(metadata.get("score") or (RISK_ORDER.get(explicit_level, 0) * 3))
    files = [str(item).replace("\\", "/") for item in expected_files or []]
    count = int(estimated_file_count or len(files) or 0)
    if count > 50:
        score += 4
        reasons.append(f"Large change set estimated: {count} files")
    elif count > 20:
        score += 2
        reasons.append(f"Broad change set estimated: {count} files")
    elif count > 8:
        score += 1
        reasons.append(f"Multi-file change estimated: {count} files")
    declared_operations = [str(item).strip().lower() for item in metadata.get("operations") or []]
    destructive_count = sum(item in {"delete", "rename", "migration", "credential_change", "deployment"} for item in declared_operations)
    if destructive_count:
        score += min(6, destructive_count * 2)
        reasons.append(f"Contract declares {destructive_count} elevated operation(s)")
    level = explicit_level or _level(score)
    if not reasons:
        reasons.append("No elevated risk was declared by the workflow contract")
    behavior = {
        "low": {"patch_mode": "atomic_apply", "approval_mode": "fully_automatic", "reviewers": 1, "checkpoint": "per_step"},
        "medium": {"patch_mode": "atomic_apply", "approval_mode": "milestones", "reviewers": 1, "checkpoint": "per_task"},
        "high": {"patch_mode": "review", "approval_mode": "review_before_apply", "reviewers": 2, "checkpoint": "per_task"},
        "critical": {"patch_mode": "dry_run", "approval_mode": "plan_and_patch_only", "reviewers": 2, "checkpoint": "per_task"},
    }[level]
    return {
        "schema": "aiwf.risk-assessment.v2",
        "level": level,
        "score": score,
        "source": "explicit_contract" if risk_metadata else "structural_metrics",
        "reasons": reasons[:20],
        "declared_operations": declared_operations[:30],
        "project_path": str(project_path) if project_path else None,
        "recommended": behavior,
        "approval_required": level in {"high", "critical"},
        "high_risk": level in {"high", "critical"},
    }


def should_pause_for_approval(risk: dict[str, Any], approval_mode: str | None, milestone: str) -> bool:
    mode = str(approval_mode or risk.get("recommended", {}).get("approval_mode") or "fully_automatic")
    if mode == "fully_automatic":
        return False
    if mode == "plan_and_patch_only":
        return milestone in {"before_execute", "before_apply"}
    if mode == "review_before_apply":
        return milestone == "before_apply"
    if mode == "milestones":
        return milestone in {"after_plan", "before_apply"} and bool(risk.get("high_risk"))
    return False


__all__ = ["RISK_ORDER", "assess_risk", "should_pause_for_approval"]
