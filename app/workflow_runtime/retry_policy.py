from __future__ import annotations

from pathlib import Path
from typing import Any

from app.runtime_files import classify_test_retry_target
from app.runtime_paths import ROOT, read_text


def retry_target_for_step(step_record: dict[str, Any], steps: list[dict[str, Any]], current_index: int) -> str | None:
    retry_from = step_record.get("retry_from_step_key") or (step_record.get("config") or {}).get("retryFromStepKey")
    if retry_from:
        return retry_from
    fail_action = step_record.get("fail_action") or "same_step"
    if fail_action == "stop":
        return None
    if fail_action == "previous_step" and current_index > 0:
        return steps[current_index - 1]["key"]
    selected = (step_record.get("config") or {}).get("failActionStepKey")
    if fail_action == "selected_step" and selected:
        return selected
    return step_record.get("key")


def retry_target_for_failure(
    run: dict[str, Any],
    step_record: dict[str, Any],
    steps: list[dict[str, Any]],
    current_index: int,
    output_dir: Path,
) -> str | None:
    key = step_record.get("key")
    if key == "run_test":
        configured = retry_target_for_step(step_record, steps, current_index)
        test_result = read_text(output_dir / "test-result.md")
        classified = classify_test_retry_target(Path(run.get("project_path") or ROOT), test_result)
        return classified if classified in {step.get("key") for step in steps} else configured
    return retry_target_for_step(step_record, steps, current_index)
