from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS

from .actions_registry import builtin_action_for_step
from .step_utils import (
    bool_config,
    step_agent_name,
    step_artifact_name,
    step_config,
    step_function_names,
    step_prompt_name,
)


class ActionDispatcherMixin:
    def action_for_step(self, run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
        key = step_record["key"]
        config = step_config(step_record)
        step_type = step_record.get("type") or config.get("type") or "ai"
        allow_interaction = bool(step_record.get("allow_interaction"))
        run_agent = str(run.get("agent") or "").strip()
        agent_name = run_agent or step_agent_name(step_record) or None

        builtin_action = builtin_action_for_step(self, run, step_record, output_dir)
        if builtin_action is not None:
            return builtin_action

        functions = step_function_names(step_record)
        function = functions[0] if functions else ""
        if len(functions) <= 1 and step_type == "validation" and function == "validate_spec":
            return lambda: self.validate_or_repair_spec(run, output_dir)
        if len(functions) <= 1 and step_type == "validation" and function == "validate_todo":
            return lambda: self.validate_or_repair_todo(run, output_dir)
        if function == "consensus_agent":
            return lambda: self.consensus_agent_step(
                run,
                key,
                step_prompt_name(step_record, f"{key}.md"),
                agent_name=agent_name,
            )
        if functions and (step_type in {"python", "validation", "check"} or any(item in PYTHON_FUNCTIONS for item in functions)):
            artifact = step_artifact_name(step_record, "") or None
            return lambda: self.functions.call_python_functions(self._run_with_step_context(run, step_record), functions, output_dir, artifact)
        if step_type == "python":
            artifact = step_artifact_name(step_record, "") or None
            return lambda: self.functions.call_python_functions(self._run_with_step_context(run, step_record), functions or ["run_pytest"], output_dir, artifact)
        if function == "require_status_pass" or step_type in {"gate", "manual"}:
            artifact = step_artifact_name(step_record, step_record.get("key", "review") + ".md")
            return lambda: asyncio.to_thread(self.functions.require_status, output_dir / artifact, "PASS")
        if step_type == "review":
            return lambda: self.review_step(
                run,
                key,
                step_prompt_name(step_record, f"{key}.md"),
                step_artifact_name(step_record, f"{key}.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
        return lambda: self.run_agent_step(
            run,
            key,
            step_prompt_name(step_record, f"{key}.md"),
            step_artifact_name(step_record, f"{key}.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
            fresh_session=not bool_config(config, "keepSameSession", True),
        )

    @staticmethod
    def _run_with_step_context(run: dict[str, Any], step_record: dict[str, Any]) -> dict[str, Any]:
        # Validators must write evidence back to the stable runtime Run object.
        # A shallow copy caused pytest/user-validation evidence to disappear
        # before the final completion gate and triggered unnecessary retries.
        run["_current_step"] = step_record
        run["_current_step_config"] = {**step_record, **step_config(step_record)}
        return run
