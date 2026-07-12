from __future__ import annotations

import re
from typing import Any


_DETERMINISTIC_CODES = {
    "TEST_DEFINITION_INVALID",
    "TEST_LAYOUT_CONFLICT",
    "VALIDATION_FILE_NOT_FOUND",
    "VALIDATION_FILE_MUTATED",
    "VALIDATION_NOT_EXECUTED",
}
_DETERMINISTIC_TEXT = (
    "pytest collection",
    "import file mismatch",
    "unresolved required fixture arguments",
    "test code must be separated",
)


def retry_feedback_blocks(feedback: str) -> list[str]:
    if not feedback.strip():
        return []
    return [
        match.group(0).strip()
        for match in re.finditer(
            r"^## Retry Feedback for .*?(?=^## Retry Feedback for |\Z)",
            feedback,
            flags=re.MULTILINE | re.DOTALL,
        )
    ]


def latest_retry_feedback_block(feedback: str) -> str:
    blocks = retry_feedback_blocks(feedback)
    return blocks[-1] if blocks else ""


def latest_feedback_task_id(feedback: str) -> str:
    block = latest_retry_feedback_block(feedback)
    if not block:
        return ""
    match = re.search(r"\bTASK-\d{3}\b", block)
    return match.group(0) if match else ""


def is_generic_task_loop_feedback(feedback: str) -> bool:
    """Return whether a synthetic repair task is genuinely useful.

    Deterministic test/layout/validation errors already have a precise owning
    step. Sending them through a synthetic implementation task wastes small
    model retries and can produce NO_FILE_CHANGE loops.
    """
    block = latest_retry_feedback_block(feedback)
    if not block.strip() or re.search(r"\bTASK-\d{3}\b", block):
        return False
    error_section = re.search(r"### Error message to fix\s*(.*)$", block, flags=re.DOTALL | re.IGNORECASE)
    if error_section is not None and not error_section.group(1).strip():
        return False
    upper = block.upper()
    lower = block.lower()
    if any(code in upper for code in _DETERMINISTIC_CODES):
        return False
    if any(marker in lower for marker in _DETERMINISTIC_TEXT):
        return False
    return True


def append_generic_repair_task(tasks: list[dict[str, Any]], *, owner: str) -> list[dict[str, Any]]:
    used_ids = {str(task.get("id") or "") for task in tasks}
    repair_id = next((f"TASK-{number:03d}" for number in range(999, 899, -1) if f"TASK-{number:03d}" not in used_ids), "TASK-REPAIR")
    return [
        *tasks,
        {
            "id": repair_id,
            "owner": owner,
            "title": "Repair assembled project from latest workflow failure feedback",
            "_generic_repair_task": True,
        },
    ]


__all__ = [
    "append_generic_repair_task",
    "is_generic_task_loop_feedback",
    "latest_feedback_task_id",
    "latest_retry_feedback_block",
    "retry_feedback_blocks",
]
