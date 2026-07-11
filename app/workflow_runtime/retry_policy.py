from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime_modules.files import classify_test_retry_target
from app.core.paths import ROOT, read_text
from .failure_classifier import classify_failure


def _retry_policy(step_record: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized generic retry policy for a workflow step.

    Workflow authors may use the legacy flat keys or the clearer nested form:

    retryPolicy:
      defaultRetryTo: build
      escalateEvery: 3
      escalateTo: plan_tasks
      maxRetries: 9

    The executor still honors existing flat keys for backward compatibility.
    """
    config = step_record.get("config") or {}
    raw = config.get("retryPolicy") or step_record.get("retryPolicy") or {}
    return raw if isinstance(raw, dict) else {}


def retry_target_for_step(step_record: dict[str, Any], steps: list[dict[str, Any]], current_index: int) -> str | None:
    """Resolve retry target from workflow config, not hard-coded defaults.

    Precedence:
    1. retryPolicy.defaultRetryTo / retryFromStepKey.
    2. failAction behavior.
    3. current failed step.
    """
    config = step_record.get("config") or {}
    policy = _retry_policy(step_record)
    available_keys = {step.get("key") for step in steps}
    configured_retry_from = (
        policy.get("defaultRetryTo")
        or policy.get("retryTo")
        or step_record.get("retry_from_step_key")
        or config.get("retryFromStepKey")
    )
    if configured_retry_from and configured_retry_from in available_keys:
        return str(configured_retry_from)

    fail_action = step_record.get("fail_action") or config.get("failAction") or "same_step"
    if fail_action == "stop":
        return None
    if fail_action == "previous_step" and current_index > 0:
        return steps[current_index - 1]["key"]
    if fail_action == "selected_step":
        selected = config.get("failActionStepKey") or config.get("selectedStepKey") or config.get("retryFromStepKey") or policy.get("defaultRetryTo")
        return str(selected) if selected and selected in available_keys else step_record.get("key")
    return step_record.get("key")


def escalated_retry_target_for_step(
    step_record: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    next_retry_count: int,
) -> str | None:
    """Return the periodic escalation target when configured.

    This is a generic workflow-controller feature, not an Adaptive-specific
    hard-code.  A step can say: normally retry from `retryFromStepKey`, but on
    every Nth retry, jump to `retryEscalationStepKey` so the AI can regenerate
    earlier prompts/specs after repeated repair failures.
    """
    config = step_record.get("config") or {}
    policy = _retry_policy(step_record)
    available_keys = {step.get("key") for step in steps}
    raw_every = policy.get("escalateEvery") or step_record.get("retryEscalationEvery") or config.get("retryEscalationEvery")
    try:
        every = int(raw_every or 0)
    except (TypeError, ValueError):
        every = 0
    if every <= 0 or next_retry_count <= 0 or next_retry_count % every != 0:
        return None
    target = policy.get("escalateTo") or step_record.get("retryEscalationStepKey") or config.get("retryEscalationStepKey")
    return str(target) if target and target in available_keys else None


def retry_target_for_failure(
    run: dict[str, Any],
    step_record: dict[str, Any],
    steps: list[dict[str, Any]],
    current_index: int,
    output_dir: Path,
    *,
    next_retry_count: int | None = None,
    error: BaseException | str | None = None,
) -> str | None:
    key = str(step_record.get("key") or "")
    configured = retry_target_for_step(step_record, steps, current_index)
    failure = classify_failure(error or "", step_key=key)
    failure_code = str(failure.get("code") or "UNKNOWN")
    message = str(error or "").lower()

    # Invalid structured review output is a reviewer-format problem, not an
    # implementation or planning failure. Repair the same review step first.
    if str(step_record.get("type") or "").lower() == "review" and (
        failure_code == "INVALID_OUTPUT" or "invalid_review_output" in message or "review_mutated_project" in message
    ):
        return key

    if failure_code == "TEST_DEFINITION_INVALID":
        return "generate_tests" if "generate_tests" in {step.get("key") for step in steps} else configured

    if key == "run_test":
        test_result = read_text(output_dir / "test-result.md")
        classified = classify_test_retry_target(Path(run.get("project_path") or ROOT), test_result)
        return classified if classified in {step.get("key") for step in steps} else configured

    # Replanning is expensive and does not fix write/parser/test failures. Only
    # jump to an earlier planner when the failure explicitly says the plan/spec
    # itself is invalid or contradictory.
    allow_escalation = any(marker in message for marker in (
        "replan_required",
        "plan_invalid",
        "spec_conflict",
        "task definition is incomplete",
    ))
    if next_retry_count is not None and allow_escalation:
        escalated = escalated_retry_target_for_step(step_record, steps, next_retry_count=next_retry_count)
        if escalated:
            return escalated
    return configured
