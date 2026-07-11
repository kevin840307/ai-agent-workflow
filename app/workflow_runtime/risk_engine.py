from __future__ import annotations

import re
from pathlib import Path
from typing import Any

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

CRITICAL_TERMS = {
    "production database", "drop table", "delete database", "credential rotation", "private key",
    "付款", "金流", "正式資料庫", "刪除資料庫", "權限系統", "authentication migration",
}
HIGH_TERMS = {
    "database migration", "schema migration", "authentication", "authorization", "security", "ci/cd",
    "deployment", "kubernetes", "terraform", "helm", "delete files", "breaking change", "public api",
    "資料庫遷移", "認證", "授權", "部署", "刪除檔案", "公開 api", "權限",
}
MEDIUM_TERMS = {
    "refactor", "multiple modules", "cross module", "dependency upgrade", "configuration", "docker",
    "重構", "跨模組", "升級依賴", "設定", "多檔", "framework",
}
SENSITIVE_PATH_PATTERNS = (
    r"(^|/)(auth|security|permissions?)(/|$)",
    r"(^|/)(migrations?|terraform|helm|k8s|deploy|ci)(/|$)",
    r"(^|/)(\.github/workflows|Dockerfile|docker-compose)",
    r"(^|/)(secrets?|credentials?)(/|$)",
)


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
) -> dict[str, Any]:
    text = str(requirement or "").lower()
    score = 0
    reasons: list[str] = []
    matched: list[str] = []
    for term in sorted(CRITICAL_TERMS):
        if term in text:
            score += 6
            matched.append(term)
            reasons.append(f"Critical operation mentioned: {term}")
    for term in sorted(HIGH_TERMS):
        if term in text:
            score += 3
            matched.append(term)
            reasons.append(f"High-risk area mentioned: {term}")
    for term in sorted(MEDIUM_TERMS):
        if term in text:
            score += 1
            matched.append(term)
            reasons.append(f"Cross-cutting change mentioned: {term}")
    files = [str(item).replace("\\", "/") for item in expected_files or []]
    for path in files:
        if any(re.search(pattern, path, flags=re.IGNORECASE) for pattern in SENSITIVE_PATH_PATTERNS):
            score += 3
            reasons.append(f"Sensitive path may change: {path}")
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
    if any(token in text for token in ("delete", "remove", "drop", "刪除", "移除")):
        score += 2
        reasons.append("Destructive operation may be required")
    if any(token in text for token in ("without test", "skip test", "不要測試", "略過測試")):
        score += 2
        reasons.append("Request may reduce deterministic validation")
    level = _level(score)
    if not reasons:
        reasons.append("No sensitive subsystem or destructive operation detected")
    behavior = {
        "low": {"patch_mode": "auto_apply", "approval_mode": "fully_automatic", "reviewers": 1, "checkpoint": "per_step"},
        "medium": {"patch_mode": "auto_apply", "approval_mode": "milestones", "reviewers": 1, "checkpoint": "per_task"},
        "high": {"patch_mode": "review", "approval_mode": "review_before_apply", "reviewers": 2, "checkpoint": "per_task"},
        "critical": {"patch_mode": "dry_run", "approval_mode": "plan_and_patch_only", "reviewers": 2, "checkpoint": "per_task"},
    }[level]
    return {
        "schema": "aiwf.risk-assessment.v1",
        "level": level,
        "score": score,
        "reasons": reasons[:20],
        "matched_terms": matched[:30],
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
