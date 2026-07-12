from __future__ import annotations

from typing import Any

AUTOPILOT_MODES = {"observe", "safe_apply", "full_autopilot"}


def autopilot_mode(run: dict[str, Any]) -> str:
    configured = str(run.get("autopilot_mode") or "").strip().lower()
    if configured in AUTOPILOT_MODES:
        return configured
    if str(run.get("patch_mode") or "") != "atomic_apply":
        return "observe"
    return "safe_apply"


def evaluate_delivery_validation(run: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    mode = autopilot_mode(run)
    profile = run.get("project_validation_profile") if isinstance(run.get("project_validation_profile"), dict) else {}
    profile_status = str(profile.get("status") or "").lower()
    results = [item for item in verification.get("results") or [] if isinstance(item, dict)]
    required = [item for item in results if bool(item.get("required"))]
    executed_count = int(verification.get("executed") or len(results))
    errors: list[str] = []

    if mode == "observe":
        errors.append("Autopilot mode is observe; project delivery is disabled.")
    if profile_status in {"draft", "stale"}:
        errors.append(f"Validation profile is {profile_status}; automatic delivery requires a verified profile.")
    if not profile and not results:
        errors.append("No validation profile or executed validation evidence is available.")
    if executed_count <= 0 or not results:
        errors.append("Post-apply validation did not execute any phase.")
    if not required:
        errors.append("Post-apply validation has no required phase.")
    for item in required:
        if item.get("status") != "passed":
            errors.append(f"Required validation phase did not pass: {item.get('id') or item.get('title') or 'unknown'}.")
    if verification.get("status") not in {"passed", "passed_with_baseline"}:
        errors.append(f"Post-apply validation status is {verification.get('status') or 'unknown'}.")
    if mode == "full_autopilot":
        environment = run.get("environment_health") if isinstance(run.get("environment_health"), dict) else {}
        if environment.get("status") not in {"ready", "ok"}:
            errors.append("Full autopilot requires a ready environment-health result.")
        # Missing profile status is accepted only for explicitly run-bound
        # profiles with required phases, preserving direct/manual API use.
        if profile_status not in {"verified", "trusted"}:
            errors.append("Full autopilot requires a verified or trusted validation profile.")

    return {
        "schema": "aiwf.autopilot-delivery-policy.v1",
        "mode": mode,
        "allowed": not errors,
        "profile_status": profile_status or None,
        "executed_count": executed_count,
        "required_count": len(required),
        "errors": errors,
    }


__all__ = ["AUTOPILOT_MODES", "autopilot_mode", "evaluate_delivery_validation"]
