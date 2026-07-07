from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from app.auto_workflow import orchestrator
from app.runtime_modules.errors import UserInputRequired, ValidationError, WorkflowError
from app.runtime_modules.files import (
    apply_build_files,
    failure_feedback_for_step,
    apply_extracted_files,
    extract_build_files,
    project_content_snapshot,
    project_file_snapshot,
    changed_snapshot_paths,
    files_from_changed_snapshot,
    render_file_blocks,
    project_has_user_files,
    project_overview,
    project_profile,
    render_project_index_markdown,
    only_test_files,
    non_test_files,
    should_ask_for_spec_input,
    snapshot_changed,
    restore_project_content_snapshot,
    spec_input_questions,
    split_build_files,
    render_generic_spec_from_requirement,
    render_generic_todo_from_spec,
    build_generic_python_import_smoke_test,
    build_validation_script_pytest_wrapper,
    existing_validation_scripts,
    validate_build_files_do_not_overwrite_validation_scripts,
    validate_build_files_are_not_tests,
    validate_generated_code_files_are_clean,
    validate_generated_test_files,
    validate_test_code_is_separate,
)
from app.core.paths import ROOT, read_text, write_text
from app.security.workspace_guard import resolve_project_relative_write
from app.security.agent_project_config import ensure_agent_project_configs
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionError

from .actions_registry import builtin_action_for_step
from .action_helpers import (
    config_for_step,
    fresh_session_for_step,
    is_adaptive_workflow,
    is_auto_development_workflow,
    is_general_auto_development_workflow,
)
from .agent_step_runner import AgentStepRunner
from .step_utils import (
    bool_config,
    normalize_artifact_name,
    step_agent_name,
    step_artifact_name,
    step_config,
    step_prompt_name,
    step_review_mode,
    step_function_name,
    step_function_names,
)


class ConsensusActionsMixin:
    async def consensus_agent_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        *,
        agent_name: str | None = None,
    ) -> None:
        """Run multiple agent generations with per-agent validation/retry inside one visible workflow step."""
        output_dir = Path(run["workspace"]) / "output"
        input_dir = Path(run["workspace"]) / "input"
        step_record = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        config = step_config(step_record)
        agent_count = int(config.get("agentCount") or 3)
        max_retries = int(config.get("agentMaxRetries") or config.get("maxRetries") or 3)
        prompt_name = step_prompt_name(step_record, prompt_name)
        agent_name = agent_name or step_agent_name(step_record) or "qwen"
        function = str(config.get("candidateValidator") or config.get("innerValidator") or config.get("function") or "").strip()
        artifact_pattern = str(
            config.get("artifactPattern")
            or config.get("outputPattern")
            or config.get("filename")
            or f"{step_key}-agent-{{index}}.md"
        )
        fresh_session_per_agent = bool_config(config, "freshSessionPerAgent", True)

        for agent_index in range(1, agent_count + 1):
            artifact = normalize_artifact_name(
                artifact_pattern
                .replace("{index}", str(agent_index))
                .replace("{n}", str(agent_index))
                .replace("*", str(agent_index), 1)
            )
            last_error: Exception | None = None
            for attempt in range(1, max_retries + 1):
                await self.log(run, f"{step_key}: agent {agent_index}/{agent_count} attempt {attempt}/{max_retries}")
                try:
                    await self.run_agent_step(
                        run,
                        step_key,
                        prompt_name,
                        artifact,
                        allow_interaction=False,
                        agent_name=agent_name,
                        fresh_session=fresh_session_per_agent,
                    )
                    if function and function != "consensus_agent":
                        await self.functions.call_python_function(run, function, output_dir, artifact)
                        await self.log(run, f"{step_key}: agent {agent_index} validated {artifact} with {function}")
                    else:
                        await self.log(run, f"{step_key}: agent {agent_index} wrote {artifact}")
                    last_error = None
                    break
                except UserInputRequired:
                    raise
                except Exception as exc:
                    last_error = exc
                    feedback_path = input_dir / "failure-feedback.md"
                    previous = read_text(feedback_path)
                    feedback = (
                        f"## Retry Feedback for {step_key}\n\n"
                        f"- Failed internal agent: {agent_index}\n"
                        f"- Retry attempt: {attempt}/{max_retries}\n"
                        f"- Artifact: {artifact}\n\n"
                        "Error message to fix:\n\n"
                        f"{str(exc).strip()}\n\n"
                    )
                    write_text(feedback_path, previous + ("\n" if previous.strip() else "") + feedback)
                    await self.refresh_artifacts(run["id"])
                    await self.log(run, f"{step_key}: agent {agent_index} failed attempt {attempt}/{max_retries}: {exc}")
            if last_error is not None:
                raise WorkflowError(
                    f"{step_key}: agent {agent_index} failed after {max_retries} attempt(s): {last_error}"
                ) from last_error

    async def consensus_security_scan_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "00_security_candidate_scan.md",
        *,
        agent_name: str | None = None,
    ) -> None:
        await self.consensus_agent_step(
            run,
            "consensus_security_scan",
            prompt_name,
            agent_name=agent_name,
        )
