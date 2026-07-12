from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from app.core.paths import AI_WORKFLOW_DIR, atomic_write_text, utc_now
from app.workflow_runtime.validators.plan import build_validation_plan, execute_validation_plan

PROFILE_ROOT = AI_WORKFLOW_DIR / "project-validation-profiles"
DESCRIPTOR_NAMES = {
    "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "requirements.txt",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "gradlew", "gradlew.bat", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "global.json", "Directory.Build.props", "Directory.Build.targets", "validation.py",
}
DESCRIPTOR_SUFFIXES = {".sln", ".csproj", ".fsproj", ".vbproj"}


def _project_key(project: Path) -> str:
    return hashlib.sha256(str(project).casefold().encode("utf-8", errors="replace")).hexdigest()[:24]


def profile_path(project_path: str | Path) -> Path:
    project = Path(project_path).expanduser().resolve()
    return PROFILE_ROOT / f"{_project_key(project)}.json"


def _descriptor_files(project: Path) -> list[Path]:
    files: list[Path] = []
    for path in project.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", ".ai-workflow", "node_modules", "target", "build", "dist", "__pycache__"} for part in path.parts):
            continue
        if path.name in DESCRIPTOR_NAMES or path.suffix.lower() in DESCRIPTOR_SUFFIXES:
            files.append(path)
    return sorted(files)


def project_descriptor_fingerprint(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for path in _descriptor_files(project):
        rel = path.relative_to(project).as_posix()
        try:
            content = path.read_bytes()
        except OSError:
            continue
        file_hash = hashlib.sha256(content).hexdigest()
        entries.append({"path": rel, "sha256": file_hash, "size": len(content)})
        digest.update(rel.encode("utf-8", errors="replace"))
        digest.update(file_hash.encode("ascii"))
    return {
        "schema": "aiwf.project-descriptor-fingerprint.v1",
        "value": digest.hexdigest(),
        "files": entries,
    }


def _profile_phases(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for phase in plan.get("phases") or []:
        result.append({
            "id": phase.get("id"),
            "title": phase.get("title"),
            "category": phase.get("category"),
            "command": list(phase.get("command") or []),
            "required": bool(phase.get("required", True)),
            "detected_by": list(phase.get("detected_by") or []),
        })
    return result


def create_detected_profile(project_path: str | Path) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    plan = build_validation_plan(project)
    now = utc_now()
    return {
        "schema": "aiwf.project-validation-profile.v1",
        "project_path": str(project),
        "project_key": _project_key(project),
        "status": "draft",
        "source": "auto_detected",
        "primary_validator": plan.get("primary_validator"),
        "phases": _profile_phases(plan),
        "baseline_categories": ["build", "test", "configuration", "syntax"],
        "fast_categories": ["build", "focused_test", "syntax", "configuration"],
        "full_categories": ["build", "test", "lint", "typecheck", "configuration", "syntax", "custom"],
        "descriptor_fingerprint": project_descriptor_fingerprint(project),
        "verification": None,
        "successful_verifications": 0,
        "created_at": now,
        "updated_at": now,
    }


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    project = Path(str(profile.get("project_path") or "")).expanduser().resolve()
    payload = deepcopy(profile)
    payload["project_path"] = str(project)
    payload["project_key"] = _project_key(project)
    payload["updated_at"] = utc_now()
    path = profile_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def _normalize_loaded(profile: dict[str, Any], project: Path) -> dict[str, Any]:
    payload = deepcopy(profile)
    payload.setdefault("schema", "aiwf.project-validation-profile.v1")
    payload["project_path"] = str(project)
    payload["project_key"] = _project_key(project)
    payload.setdefault("status", "draft")
    payload.setdefault("phases", [])
    payload.setdefault("successful_verifications", 0)
    return payload


def load_profile(project_path: str | Path, *, create: bool = True) -> dict[str, Any] | None:
    project = Path(project_path).expanduser().resolve()
    path = profile_path(project)
    if not path.is_file():
        if not create:
            return None
        return save_profile(create_detected_profile(project))
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        if not create:
            return None
        return save_profile(create_detected_profile(project))
    if not isinstance(raw, dict):
        return save_profile(create_detected_profile(project)) if create else None
    profile = _normalize_loaded(raw, project)
    current = project_descriptor_fingerprint(project)
    previous = (profile.get("descriptor_fingerprint") or {}).get("value")
    if previous and previous != current.get("value"):
        profile["status"] = "stale"
        profile["stale_reason"] = "Project build, test, or validation descriptors changed."
        profile["current_descriptor_fingerprint"] = current
    return profile


def refresh_profile(project_path: str | Path, *, preserve_custom_phases: bool = True) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    existing = load_profile(project, create=False)
    detected = create_detected_profile(project)
    if existing and preserve_custom_phases and existing.get("source") == "user_confirmed" and existing.get("phases"):
        detected["phases"] = deepcopy(existing["phases"])
        detected["source"] = "user_confirmed"
    return save_profile(detected)


def update_profile(project_path: str | Path, patch: dict[str, Any]) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    profile = load_profile(project, create=True) or create_detected_profile(project)
    allowed = {
        "phases", "baseline_categories", "fast_categories", "full_categories", "source",
        "notes", "environment", "artifacts", "scope",
    }
    for key in allowed:
        if key in patch:
            profile[key] = deepcopy(patch[key])
    profile["source"] = "user_confirmed"
    profile["status"] = "draft"
    profile["verification"] = None
    profile["descriptor_fingerprint"] = project_descriptor_fingerprint(project)
    profile.pop("stale_reason", None)
    profile.pop("current_descriptor_fingerprint", None)
    return save_profile(profile)


def validation_plan_from_profile(
    project_path: str | Path,
    profile: dict[str, Any] | None,
    *,
    categories: Iterable[str] | None = None,
) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    if not profile or not profile.get("phases"):
        return build_validation_plan(project)
    include = {str(item) for item in categories or []}
    phases: list[dict[str, Any]] = []
    for raw in profile.get("phases") or []:
        category = str(raw.get("category") or "custom")
        if include and category not in include:
            continue
        command = [str(item) for item in raw.get("command") or []]
        phases.append({
            "id": str(raw.get("id") or f"profile-{len(phases) + 1}"),
            "title": str(raw.get("title") or raw.get("id") or "Validation"),
            "category": category,
            "command": command,
            "command_text": " ".join(command),
            "required": bool(raw.get("required", True)),
            "detected_by": list(raw.get("detected_by") or ["project validation profile"]),
        })
    return {
        "schema": "aiwf.validation-plan.v1",
        "project_path": str(project),
        "primary_validator": profile.get("primary_validator"),
        "profile_status": profile.get("status"),
        "phases": phases,
        "impacted_tests": {"schema": "aiwf.impacted-tests.v1", "tests": [], "confidence": "profile"},
    }


def record_profile_verification(
    project_path: str | Path,
    profile: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    payload = deepcopy(profile)
    count = int(payload.get("successful_verifications") or 0)
    if result.get("status") in {"passed", "passed_with_baseline"}:
        count += 1
        payload["status"] = "trusted" if count >= 3 else "verified"
    else:
        payload["status"] = "draft"
    payload["successful_verifications"] = count
    payload["verification"] = {
        "status": result.get("status"),
        "verified_at": utc_now(),
        "required_failures": result.get("required_failures"),
        "executed": result.get("executed"),
        "results": result.get("results"),
    }
    payload["descriptor_fingerprint"] = project_descriptor_fingerprint(project)
    payload.pop("stale_reason", None)
    payload.pop("current_descriptor_fingerprint", None)
    return save_profile(payload)


async def verify_profile(project_path: str | Path, *, timeout_sec: int = 900) -> dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    profile = load_profile(project, create=True) or create_detected_profile(project)
    result = await execute_validation_plan(project, timeout_sec=timeout_sec, fail_fast=False, profile=profile)
    saved = record_profile_verification(project, profile, result)
    return {"profile": saved, "validation": result}


__all__ = [
    "create_detected_profile", "load_profile", "profile_path", "project_descriptor_fingerprint",
    "record_profile_verification", "refresh_profile", "save_profile", "update_profile", "validation_plan_from_profile", "verify_profile",
]
