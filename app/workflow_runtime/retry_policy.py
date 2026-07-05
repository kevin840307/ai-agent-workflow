from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime_modules.files import classify_test_retry_target
from app.core.paths import ROOT, read_text


def retry_target_for_step(step_record: dict[str, Any], steps: list[dict[str, Any]], current_index: int) -> str | None:
    """Resolve retry target from workflow.json, not hard-coded defaults.

    Precedence:
    1. retryFromStepKey explicitly configured in workflow.json.
    2. failAction behavior.
    3. current failed step.
    """
    config = step_record.get("config") or {}
    available_keys = {step.get("key") for step in steps}
    configured_retry_from = step_record.get("retry_from_step_key") or config.get("retryFromStepKey")
    if configured_retry_from and configured_retry_from in available_keys:
        return str(configured_retry_from)

    fail_action = step_record.get("fail_action") or config.get("failAction") or "same_step"
    if fail_action == "stop":
        return None
    if fail_action == "previous_step" and current_index > 0:
        return steps[current_index - 1]["key"]
    if fail_action == "selected_step":
        selected = config.get("failActionStepKey") or config.get("selectedStepKey") or config.get("retryFromStepKey")
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
    available_keys = {step.get("key") for step in steps}
    raw_every = step_record.get("retryEscalationEvery") or config.get("retryEscalationEvery")
    try:
        every = int(raw_every or 0)
    except (TypeError, ValueError):
        every = 0
    if every <= 0 or next_retry_count <= 0 or next_retry_count % every != 0:
        return None
    target = step_record.get("retryEscalationStepKey") or config.get("retryEscalationStepKey")
    return str(target) if target and target in available_keys else None


def retry_target_for_failure(
    run: dict[str, Any],
    step_record: dict[str, Any],
    steps: list[dict[str, Any]],
    current_index: int,
    output_dir: Path,
    *,
    next_retry_count: int | None = None,
) -> str | None:
    key = step_record.get("key")
    configured = retry_target_for_step(step_record, steps, current_index)
    if next_retry_count is not None:
        escalated = escalated_retry_target_for_step(step_record, steps, next_retry_count=next_retry_count)
        if escalated:
            return escalated
    if key == "run_test":
        test_result = read_text(output_dir / "test-result.md")
        classified = classify_test_retry_target(Path(run.get("project_path") or ROOT), test_result)
        return classified if classified in {step.get("key") for step in steps} else configured
    return configured
