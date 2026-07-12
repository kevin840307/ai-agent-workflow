from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.runtime_modules.errors import UserInputRequired, WorkflowError
from app.runtime_modules.files import (
    changed_snapshot_paths,
    files_from_changed_snapshot,
    is_owned_test_file_path,
    project_file_snapshot,
    restore_project_content_snapshot,
    restore_selected_project_paths,
    split_build_files,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.security.agent_project_config import ensure_agent_project_configs
from app.workflow_runtime.failure_classifier import classify_failure

from .action_helpers import config_for_step
from .step_utils import bool_config, normalize_artifact_name


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

    async def _run_task_agent_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        artifact: str,
        *,
        agent_name: str | None = None,
        fresh_session: bool = False,
    ) -> str:
        config = self._config_for_step(run, step_key)
        raw = config.get("taskTimeoutSec") or config.get("task_timeout_sec") or 300
        try:
            timeout = max(30.0, float(raw))
        except (TypeError, ValueError):
            timeout = 300.0
        return await asyncio.wait_for(
            self.run_agent_step(
                run,
                step_key,
                prompt_name,
                artifact,
                agent_name=agent_name,
                fresh_session=fresh_session,
            ),
            timeout=timeout,
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
            validate_generated_test_files(files, project_dir=project_dir)
        if forbid_test_files:
            validate_build_files_are_not_tests(files)
        return files

    def _enforce_phase_file_ownership(
        self,
        project_dir: Path,
        before_content: dict[str, bytes],
        files: list[tuple[str, str]],
        *,
        phase: str,
        protected_names: set[str] | None = None,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        """Keep only files owned by the current workflow phase.

        Build owns production/config/source files. Generate Tests owns canonical
        pytest files under tests/. Files written by the wrong phase are restored
        individually from the pre-step snapshot, preserving valid edits from the
        same agent attempt.
        """
        if phase == "build":
            accepted, rejected = split_build_files(files)
            protected = {name.strip().lower() for name in (protected_names or set()) if name.strip()}
            if protected:
                protected_files = [item for item in accepted if Path(item[0]).name.strip().lower() in protected]
                accepted = [item for item in accepted if Path(item[0]).name.strip().lower() not in protected]
                rejected.extend(protected_files)
        elif phase == "generate_tests":
            existing_paths = before_content.keys()
            accepted = [
                item for item in files
                if is_owned_test_file_path(item[0], existing_paths=existing_paths)
            ]
            rejected = [
                item for item in files
                if not is_owned_test_file_path(item[0], existing_paths=existing_paths)
            ]
        else:
            return files, []
        rejected_paths = [rel_path for rel_path, _ in rejected]
        restored = restore_selected_project_paths(project_dir, before_content, rejected_paths) if rejected_paths else []
        return accepted, restored

    def _candidate_files_after_agent_failure(
        self,
        project_dir: Path,
        before: dict[str, tuple[int, int]],
        exc: Exception,
        *,
        require_test_files: bool = False,
        forbid_test_files: bool = False,
    ) -> list[tuple[str, str]]:
        if isinstance(exc, UserInputRequired):
            return []
        # The filesystem is the source of truth. A provider can return malformed
        # summary text or time out after its edit tool already completed. Preserve
        # and validate those candidate edits instead of declaring the task failed.
        files = self._direct_edit_files_from_snapshot(
            project_dir,
            before,
            project_file_snapshot(project_dir),
            require_test_files=require_test_files,
            forbid_test_files=forbid_test_files,
        )
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

    async def _restore_failed_project_attempt(
        self,
        run: dict[str, Any],
        project_dir: Path,
        snapshot: dict[str, bytes],
        label: str,
        exc: Exception,
    ) -> None:
        failure = classify_failure(exc, step_key=label)
        code = str(failure.get("code") or "UNKNOWN")
        rollback_codes = {
            "VALIDATION_FAILED",
            "TEST_FAILED",
            "PROJECT_GUARD_BLOCKED",
            "EXPECTED_FILES_MISSING",
        }
        # Agent output/session/parser failures can happen after the CLI already
        # completed valid edits. Preserve those candidate files and let the
        # deterministic diff/test gates decide whether repair is needed.
        if code not in rollback_codes:
            await self.log(
                run,
                f"{label}: preserved candidate project files after {code}; deterministic validation will decide acceptance: {str(exc)[:500]}",
            )
            return
        restore_project_content_snapshot(project_dir, snapshot)
        # A rolled-back filesystem no longer matches the model's conversation.
        # Force exactly the next agent call onto a fresh session.
        run["_fresh_agent_session_once"] = True
        await self.log(run, f"{label}: restored project files after deterministic {code} failure: {str(exc)[:500]}")
