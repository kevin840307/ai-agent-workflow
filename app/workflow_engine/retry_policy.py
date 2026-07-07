from __future__ import annotations

from typing import Any

from app.workflow_runtime.retry_policy import retry_target_for_failure


class WorkflowRetryPolicy:
    def target_for_failure(self, run: dict[str, Any], step: dict[str, Any], steps: list[dict[str, Any]], index: int, output_dir, *, next_retry_count: int | None = None) -> str | None:
        return retry_target_for_failure(run, step, steps, index, output_dir, next_retry_count=next_retry_count)
