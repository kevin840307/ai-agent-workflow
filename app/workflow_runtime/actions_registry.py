from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.workflow_runtime.step_utils import (
    step_agent_name,
    step_artifact_name,
    step_config,
    step_function_names,
    step_prompt_name,
)

ActionCallable = Callable[[], Awaitable[None]]


def builtin_action_for_step(actions: Any, run: dict[str, Any], step_record: dict[str, Any], output_dir: Path) -> ActionCallable | None:
    """Return specialized built-in workflow actions by step key.

    Keeping this dispatch table outside ``actions.py`` makes the large action
    implementation easier to reason about without changing the behavior of the
    individual step handlers.
    """
    key = step_record["key"]
    config = step_config(step_record)
    step_type = step_record.get("type") or config.get("type") or "ai"
    allow_interaction = bool(step_record.get("allow_interaction"))
    run_agent = str(run.get("agent") or "").strip()
    agent_name = run_agent or step_agent_name(step_record) or None

    registry: dict[str, ActionCallable] = {
        "prepare_project": lambda: actions.prepare_project_step(
            run,
            step_prompt_name(step_record, "00_prepare.md"),
            step_artifact_name(step_record, "architecture.md"),
            agent_name=agent_name,
        ),
        "generate_spec": lambda: actions.generate_spec_step(
            run,
            step_prompt_name(step_record, "01_spec.md"),
            step_artifact_name(step_record, "spec.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        ),
        "validate_spec": lambda: actions.validate_or_repair_spec(run, output_dir),
        "review_spec": lambda: actions.review_step(
            run,
            key,
            step_prompt_name(step_record, "02_review_spec.md"),
            step_artifact_name(step_record, "spec-review.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        ),
        "spec_gate": lambda: asyncio.to_thread(actions.functions.require_status, output_dir / step_artifact_name(step_record, "spec-review.md"), "PASS"),
        "generate_todo": lambda: actions.generate_todo_step(
            run,
            step_prompt_name(step_record, "03_todo.md"),
            step_artifact_name(step_record, "todo.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
            step_key="generate_todo",
        ),
        "plan_tasks": lambda: actions.generate_todo_step(
            run,
            step_prompt_name(step_record, "01_plan_tasks.md"),
            step_artifact_name(step_record, "todo.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
            step_key="plan_tasks",
        ),
        "validate_todo": lambda: actions.validate_or_repair_todo(run, output_dir),
        "review_todo": lambda: actions.review_step(
            run,
            key,
            step_prompt_name(step_record, "04_review_todo.md"),
            step_artifact_name(step_record, "todo-review.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        ),
        "implementation_review": lambda: actions.review_step(
            run,
            key,
            step_prompt_name(step_record, "02_implementation_review.md"),
            step_artifact_name(step_record, "implementation-review.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        ),
        "todo_gate": lambda: asyncio.to_thread(actions.functions.require_status, output_dir / step_artifact_name(step_record, "todo-review.md"), "PASS"),
        "generate_tests": lambda: actions.generate_tests_step(
            run,
            step_prompt_name(step_record, "07_test.md"),
            step_artifact_name(step_record, "test-plan.md"),
            agent_name=agent_name,
        ),
        "build": lambda: actions.build_step(
            run,
            step_prompt_name(step_record, "05_build.md"),
            step_artifact_name(step_record, "build-result.md"),
            agent_name=agent_name,
        ),
        "generate_task_prompts": lambda: actions.generate_task_prompts_step(
            run,
            step_prompt_name(step_record, "00_generate_task_prompts.md"),
            step_artifact_name(step_record, "task-prompts.md"),
            agent_name=agent_name,
        ),
        "auto_generation": lambda: actions.adaptive_generation_step(
            run,
            step_prompt_name(step_record, "00_auto_generation.md"),
            step_artifact_name(step_record, "auto-generation-result.md"),
            agent_name=agent_name,
        ),
        "ai_review": lambda: (
            actions.adaptive_ai_review_with_validation_step(
                run,
                step_prompt_name(step_record, "01_ai_review.md"),
                step_artifact_name(step_record, "ai-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
            if actions._is_adaptive_workflow(run)
            else actions.review_step(
                run,
                key,
                step_prompt_name(step_record, "01_ai_review.md"),
                step_artifact_name(step_record, "ai-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
        ),
        "run_test": lambda: actions.functions.call_python_functions(
            actions._run_with_step_context(run, step_record),
            step_function_names(step_record) or ["run_pytest"],
            output_dir,
        ),
        "consensus_security_scan": lambda: actions.consensus_security_scan_step(
            run,
            step_prompt_name(step_record, "00_security_candidate_scan.md"),
            agent_name=agent_name,
        ),
        "consensus_agent": lambda: actions.consensus_agent_step(
            run,
            key,
            step_prompt_name(step_record, f"{key}.md"),
            agent_name=agent_name,
        ),
        "final_review": lambda: (
            actions.final_review_step(run, step_artifact_name(step_record, "final-review.md"))
            if step_type == "python"
            else actions.review_step(
                run,
                key,
                step_prompt_name(step_record, "05_final_review.md"),
                step_artifact_name(step_record, "final-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
        ),
        "final_gate": lambda: asyncio.to_thread(actions.functions.require_status, output_dir / step_artifact_name(step_record, "final-review.md"), "PASS"),
    }
    return registry.get(key)


__all__ = ["builtin_action_for_step"]
