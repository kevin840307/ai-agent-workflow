from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.paths import utc_now, write_text
from app.workflow_runtime.project_validation_profile import load_profile, record_profile_verification
from app.workflow_runtime.environment_health import inspect_environment
from app.runtime_modules.errors import WorkflowError
from app.workflow_runtime.validators import execute_validation_plan


async def ensure_autopilot_preflight(
    run: dict[str, Any],
    *,
    update_run: Callable[[str, Callable[[dict[str, Any]], Any]], Awaitable[dict[str, Any]]],
    log: Callable[[dict[str, Any], str], Awaitable[None]],
) -> dict[str, Any]:
    """Create reusable validation context before the first agent edits a project.

    This is deterministic controller work only. It never writes implementation
    files and it runs in the run's effective Project Path so Qwen/OpenCode still
    own all source changes.
    """
    if run.get("autopilot_preflight") and run.get("baseline_validation"):
        return run
    project = Path(run.get("project_path") or run.get("original_project_path") or ".").expanduser().resolve()
    profile = load_profile(run.get("original_project_path") or project, create=True)
    environment_health = inspect_environment(project, profile)
    timeout = max(30, min(int(os.environ.get("AIWF_BASELINE_TIMEOUT_SEC", "900")), 86400))
    categories = set((profile or {}).get("baseline_categories") or []) or None
    await log(run, "autopilot: establishing project validation baseline")
    baseline = await execute_validation_plan(
        project,
        timeout_sec=timeout,
        categories=categories,
        fail_fast=False,
        profile=profile,
    )
    if profile and baseline.get("executed"):
        profile = record_profile_verification(run.get("original_project_path") or project, profile, baseline)
    delivery_ready = bool(
        baseline.get("executed")
        and baseline.get("status") in {"passed", "passed_with_baseline"}
        and (profile or {}).get("status") in {"verified", "trusted"}
    )
    preflight = {
        "schema": "aiwf.autopilot-preflight.v2",
        "status": "ready" if delivery_ready else "review_only",
        "delivery_ready": delivery_ready,
        "project_path": str(project),
        "validation_profile_status": (profile or {}).get("status"),
        "baseline_status": baseline.get("status"),
        "baseline_required_failures": baseline.get("required_failures"),
        "environment_status": environment_health.get("status"),
        "environment_blockers": environment_health.get("blockers"),
        "completed_at": utc_now(),
    }

    def persist(item: dict[str, Any]) -> None:
        item["project_validation_profile"] = profile
        item["baseline_validation"] = baseline
        item["environment_health"] = environment_health
        item["autopilot_preflight"] = preflight
        if not delivery_ready and str(item.get("patch_mode") or "") == "atomic_apply":
            item["patch_mode"] = "review"
            item["autopilot_mode"] = "observe"
            item["autopilot_delivery_blockers"] = [
                "A verified validation profile with an executed passing baseline is required for automatic delivery."
            ]
        item["updated_at"] = utc_now()

    latest = await update_run(run["id"], persist)
    target = latest or run
    output_dir = Path(run["workspace"]) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text(output_dir / "project-validation-profile.json", json.dumps(profile, indent=2, ensure_ascii=False))
    write_text(output_dir / "baseline-validation-result.json", json.dumps(baseline, indent=2, ensure_ascii=False))
    write_text(output_dir / "environment-health.json", json.dumps(environment_health, indent=2, ensure_ascii=False))
    write_text(output_dir / "autopilot-preflight.json", json.dumps(preflight, indent=2, ensure_ascii=False))
    await log(target, f"autopilot: baseline {baseline.get('status')} with {baseline.get('required_failures', 0)} required failure(s)")
    if not delivery_ready:
        await log(target, "autopilot: automatic delivery downgraded to review-only because validation evidence is not trusted")
    if environment_health.get("status") == "blocked":
        raise WorkflowError("AUTOPILOT_ENVIRONMENT_NOT_READY: " + ", ".join(environment_health.get("blockers") or []))
    return target


__all__ = ["ensure_autopilot_preflight"]
