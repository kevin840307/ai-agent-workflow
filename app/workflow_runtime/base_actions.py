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


class BaseAgentActionsMixin:
    async def run_agent_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool | None = None,
        agent_name: str | None = None,
        fresh_session: bool = False,
    ) -> str:
        return await self.agent_runner.run(
            run,
            step_key,
            prompt_name,
            normalize_artifact_name(artifact),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
            fresh_session=fresh_session,
        )

    async def run_qwen_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool | None = None,
    ) -> None:
        await self.run_agent_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction, agent_name="qwen")

    async def _ensure_project_agent_configs(self, run: dict[str, Any], project_dir: Path) -> None:
        written = ensure_agent_project_configs(project_dir)
        rels = []
        for path in written:
            try:
                rels.append(path.relative_to(project_dir).as_posix())
            except ValueError:
                rels.append(str(path))
        await self.log(
            run,
            "agent_guard: project cwd/write root is "
            + str(project_dir.expanduser().resolve())
            + "; read policy=unrestricted; write policy=project_only; dangerous operations=denied"
        )
        if rels:
            await self.log(run, "agent_guard: wrote project-local CLI guard config: " + ", ".join(rels))

    def _direct_edit_files_from_snapshot(
        self,
        project_dir: Path,
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
        *,
        require_test_files: bool = False,
        forbid_test_files: bool = False,
    ) -> list[tuple[str, str]]:
        changed = changed_snapshot_paths(before, after)
        if not changed:
            return []
        files = files_from_changed_snapshot(project_dir, changed)
        if require_test_files:
            validate_generated_test_files(files)
        if forbid_test_files:
            validate_build_files_are_not_tests(files)
        return files

    @staticmethod
    def _validate_build_direct_files_are_substantive(run: dict[str, Any], direct_files: list[tuple[str, str]]) -> None:
        config = config_for_step(run, "build")
        if not bool_config(config, "requireSubstantiveBuild", False):
            return
        if bool_config(config, "allowDocumentationOnlyBuild", False):
            return
        doc_suffixes = {".md", ".markdown", ".rst", ".txt", ".adoc"}
        substantive = [
            rel_path
            for rel_path, _content in direct_files
            if Path(rel_path).suffix.lower() not in doc_suffixes
        ]
        if substantive:
            return
        changed = ", ".join(rel_path for rel_path, _content in direct_files) or "none"
        raise WorkflowError(
            "build only changed documentation/text files, but this workflow requires a concrete project artifact. "
            f"Changed files: {changed}. Create or modify the actual production/config/source artifact, or enable "
            "allowDocumentationOnlyBuild for documentation-only workflows."
        )

    def _file_blocks_allowed_as_direct_edits(self, run: dict[str, Any] | None = None, step_key: str = "") -> bool:
        """Return whether the platform may materialize agent FILE blocks.

        Real Qwen/OpenCode workflow runs should prove work through actual
        project-file diffs.  FILE/CONTENT/END_FILE materialization is kept as
        an explicit mock/test compatibility path only, so production behavior
        stays close to normal CLI agent usage.
        """
        env_value = os.environ.get("QWEN_WORKFLOW_ALLOW_FILE_BLOCK_MATERIALIZATION", "").lower()
        if env_value in {"1", "true", "yes", "on"}:
            return True

        if run:
            if bool(run.get("allow_file_block_materialization") or run.get("_allow_file_block_materialization")):
                return True
            config = self._config_for_step(run, step_key) if step_key else {}
            if bool_config(config, "allowFileBlockMaterialization", False):
                return True

        if any(
            os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}
            for name in ("QWEN_MOCK", "OPENCODE_MOCK", "GENERIC_AGENT_MOCK")
        ):
            return True

        # Unit tests and deterministic local fakes often inject a tiny runner
        # instead of the real AgentStepRunner.  Keep their FILE-block fixtures
        # working without enabling fallback in real CLI runs.
        return not isinstance(self.agent_runner, AgentStepRunner)

    async def _restore_failed_project_attempt(
        self,
        run: dict[str, Any],
        project_dir: Path,
        snapshot: dict[str, bytes],
        label: str,
        exc: Exception,
    ) -> None:
        restore_project_content_snapshot(project_dir, snapshot)
        await self.log(run, f"{label}: restored project files after failed attempt: {str(exc)[:500]}")

    def _apply_file_blocks_for_direct_edit(
        self,
        project_dir: Path,
        output_text: str,
        *,
        run: dict[str, Any] | None = None,
        step_key: str = "",
        require_test_files: bool = False,
        forbid_test_files: bool = False,
        validation_script: str | None = None,
        fallback_scripts: list[str] | None = None,
        output_label: str = "agent file block direct edit output",
    ) -> list[tuple[str, str]]:
        if not self._file_blocks_allowed_as_direct_edits(run, step_key):
            return []
        files = extract_build_files(output_text)
        if not files:
            return []
        if require_test_files:
            validate_generated_test_files(files)
        if forbid_test_files:
            validate_build_files_are_not_tests(files)
        validate_build_files_do_not_overwrite_validation_scripts(
            project_dir,
            files,
            validation_script=validation_script,
            fallback_scripts=fallback_scripts,
        )
        adjusted: list[tuple[str, str]] = []
        for rel_path, content in files:
            normalized = rel_path.strip().strip("`").replace("\\", "/")
            target = project_dir / normalized
            if target.is_file():
                try:
                    existing = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    existing = ""
                existing_markers = self._content_markers(existing)
                new_markers = self._content_markers(content)
                missing_existing = [marker for marker in existing_markers if marker not in content]
                has_new = any(marker not in existing for marker in new_markers)
                if existing.strip() and missing_existing and has_new:
                    content = existing.rstrip() + "\n\n" + content.lstrip().rstrip() + "\n"
            adjusted.append((rel_path, content))
        apply_extracted_files(project_dir, adjusted, output_label=output_label)
        return adjusted
