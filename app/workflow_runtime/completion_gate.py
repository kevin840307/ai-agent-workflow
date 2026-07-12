from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.paths import read_text

_CODE_WORKFLOWS = {"general-auto-development", "adaptive-auto-workflow"}
_PASS = {"pass", "passed", "success", "completed", "done"}
_NEUTRAL = {"not_configured", "skipped", "not-required", "not_required"}


def _status(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _exit_zero(value: Any) -> bool:
    return value == 0 or str(value or "").strip() == "0"


def _validation_record(run: dict[str, Any], key: str) -> dict[str, Any] | None:
    for item in reversed(list(run.get("validation_results") or [])):
        if isinstance(item, dict) and str(item.get("key") or "") == key:
            return item
    return None


def _artifact_pass(path: Path) -> bool:
    text = read_text(path)
    if not text.strip():
        return False
    status_pass = bool(re.search(r"(?im)^Status:\s*PASS\s*$", text))
    exit_zero = bool(re.search(r"(?im)^Exit\s*Code:\s*0\s*$|^ExitCode:\s*0\s*$", text))
    return status_pass and exit_zero


def evaluate_completion(run: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
    """Evaluate the non-bypassable production completion contract.

    Agent prose cannot satisfy this gate. Required validators need an executed
    result with exit code 0. Optional user validation is neutral when omitted.
    """
    workflow_id = str(run.get("workflow_id") or "")
    output = output_dir or (Path(run.get("workspace") or ".") / "output")
    checks: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    if workflow_id in _CODE_WORKFLOWS:
        test = _validation_record(run, "test")
        test_ok = bool(test and _status(test.get("status")) in _PASS and _exit_zero(test.get("exit_code")))
        if not test_ok:
            test_ok = _artifact_pass(output / "test-result.md")
        user_validation = _validation_record(run, "user_validation")
        external_test_ok = bool(
            user_validation
            and _status(user_validation.get("status")) in _PASS
            and _exit_zero(user_validation.get("exit_code"))
        )
        if not test_ok and external_test_ok:
            test_ok = True
        checks["automated_tests"] = {
            "status": "PASS" if test_ok else "FAIL",
            "evidence": (
                "validation_results:test, output/test-result.md, or executed external validation"
            ),
        }
        if not test_ok:
            errors.append("Automated tests were not executed successfully with exit code 0.")

    contract = run.get("validation_contract") if isinstance(run.get("validation_contract"), dict) else None
    required = bool((contract or {}).get("required"))
    user_validation = _validation_record(run, "user_validation")
    uv_status = _status((user_validation or {}).get("status"))
    uv_ok = bool(user_validation and uv_status in _PASS and _exit_zero(user_validation.get("exit_code")))
    if not uv_ok and required:
        uv_ok = _artifact_pass(output / "external-validation-result.md") or _artifact_pass(output / "user-validation-result.md")
    if required:
        checks["user_validation"] = {
            "status": "PASS" if uv_ok else "FAIL",
            "evidence": "required validation contract + executed exit code 0",
        }
        if not uv_ok:
            errors.append("Required user validation did not pass with exit code 0.")
    else:
        neutral = not user_validation or uv_status in _NEUTRAL
        checks["user_validation"] = {
            "status": "PASS" if uv_ok else ("NOT_CONFIGURED" if neutral else "FAIL"),
            "evidence": "optional validation is neutral when not configured",
        }
        if user_validation and not uv_ok and not neutral:
            errors.append("Configured optional user validation executed but did not pass.")

    tasks = [item for item in list(run.get("tasks") or []) if isinstance(item, dict)]
    incomplete = [
        str(item.get("id") or "unknown")
        for item in tasks
        if _status(item.get("status")) in {"failed", "blocked", "pending", "running", "repairing"}
    ]
    checks["accepted_tasks"] = {
        "status": "PASS" if not incomplete else "FAIL",
        "evidence": "task status / task checkpoint records",
        "incomplete": incomplete,
    }
    if incomplete:
        errors.append("Incomplete task(s): " + ", ".join(incomplete))

    active_failures = [
        str(step.get("key") or "unknown")
        for step in list(run.get("steps") or [])
        if isinstance(step, dict) and _status(step.get("status")) in {"failed", "blocked", "waiting_input"}
    ]
    checks["step_state"] = {
        "status": "PASS" if not active_failures else "FAIL",
        "evidence": "no failed/blocked/waiting steps at completion",
        "failed_steps": active_failures,
    }
    if active_failures:
        errors.append("Unresolved step(s): " + ", ".join(active_failures))

    policy_violations = [
        item for item in list(run.get("policy_violations") or [])
        if isinstance(item, dict) and not item.get("resolved")
    ]
    checks["policy"] = {
        "status": "PASS" if not policy_violations else "FAIL",
        "evidence": "all policy violations resolved",
    }
    if policy_violations:
        errors.append("Unresolved policy violation(s) remain.")

    return {
        "schema": "aiwf.completion-gate.v1",
        "status": "PASS" if not errors else "FAIL",
        "checks": checks,
        "errors": errors,
    }


def require_completion(run: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
    result = evaluate_completion(run, output_dir=output_dir)
    if result["status"] != "PASS":
        raise RuntimeError("FINAL_COMPLETION_GATE_FAILED: " + "; ".join(result["errors"]))
    return result


__all__ = ["evaluate_completion", "require_completion"]
