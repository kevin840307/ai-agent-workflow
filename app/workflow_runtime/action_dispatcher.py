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
        scoped = dict(run)
        scoped["_current_step"] = step_record
        scoped["_current_step_config"] = {**step_record, **step_config(step_record)}
        return scoped
