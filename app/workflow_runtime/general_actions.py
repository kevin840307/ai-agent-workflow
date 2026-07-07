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


class GeneralDevelopmentActionsMixin:
    async def validate_or_repair_spec(self, run: dict[str, Any], output_dir: Path) -> None:
        self.functions.validate_spec(output_dir)

    async def validate_or_repair_todo(self, run: dict[str, Any], output_dir: Path) -> None:
        self.functions.validate_todo(output_dir)

    async def generate_spec_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "01_spec.md",
        artifact: str = "spec.md",
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
    ) -> None:
        output_dir = Path(run["workspace"]) / "output"
        input_dir = Path(run["workspace"]) / "input"
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        answers = read_text(input_dir / "answers.md")
        project_dir = Path(run.get("project_path") or ROOT)
        if allow_interaction and should_ask_for_spec_input(requirement, project_dir, answers):
            input_dir.mkdir(parents=True, exist_ok=True)
            write_text(input_dir / "questions.md", spec_input_questions(requirement, project_dir, answers))
            await self.refresh_artifacts(run["id"])
            raise UserInputRequired("generate_spec: requirement needs clarification. See input/questions.md.")
        try:
            await self.run_agent_step(run, "generate_spec", prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            self.functions.validate_spec(output_dir)
        except UserInputRequired as exc:
            answers = read_text(input_dir / "answers.md")
            if should_ask_for_spec_input(requirement, project_dir, answers):
                raise
            await self.log(run, f"generate_spec: agent asked unnecessarily, writing deterministic fallback: {exc}")
            write_text(output_dir / normalize_artifact_name(artifact), render_generic_spec_from_requirement(requirement))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_spec(output_dir)
        except (WorkflowError, ValidationError) as exc:
            await self.log(run, f"generate_spec: agent output was not valid, writing deterministic fallback: {exc}")
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            write_text(output_dir / normalize_artifact_name(artifact), render_generic_spec_from_requirement(requirement))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_spec(output_dir)

    async def generate_todo_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "03_todo.md",
        artifact: str = "todo.md",
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
        step_key: str = "generate_todo",
    ) -> None:
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        project_dir = Path(run.get("project_path") or ROOT)

        if self._is_general_auto_development_workflow(run) and step_key == "plan_tasks":
            output = await self.run_agent_step(
                run,
                step_key,
                prompt_name,
                artifact,
                allow_interaction=allow_interaction,
                agent_name=agent_name,
                fresh_session=self._fresh_session_for_step(run, step_key),
            )
            manifest = self._parse_ai_task_prompt_manifest(output, step_key="plan_tasks")
            tasks = manifest.get("tasks") or []
            self._current_project_dir = project_dir
            self._write_ai_task_prompt_manifest(output_dir, manifest, source_label="AI-generated General Auto Development SOP plan")
            await self.refresh_artifacts(run["id"])
            await self.log(run, f"plan_tasks: AI generated SPEC, todo, and {len(tasks)} task prompt(s)")
            return

        try:
            await self.run_agent_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            if step_key == "generate_todo":
                self.functions.validate_todo(output_dir)
        except UserInputRequired:
            raise
        except (WorkflowError, ValidationError) as exc:
            if self._is_auto_development_workflow(run) or step_key == "plan_tasks":
                await self.log(run, f"{step_key}: agent output was not valid and deterministic fallback is disabled: {exc}")
                raise
            await self.log(run, f"generate_todo: agent output was not valid, writing deterministic fallback: {exc}")
            write_text(output_dir / artifact, render_generic_todo_from_spec(output_dir))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_todo(output_dir)

    async def review_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
    ) -> None:
        step_record = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        config = step_config(step_record)
        mode = step_review_mode(step_record)
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)

        if mode in {"", "none", "disabled"}:
            write_text(output_dir / artifact, "Status: PASS\n\n## Review\n- Skipped because reviewMode is none.\n")
            await self.refresh_artifacts(run["id"])
            return

        if mode == "multi_agent":
            await self._run_multi_agent_review(run, step_record, prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            return

        fresh_session = mode == "new_agent" or not bool_config(config, "keepSameSession", True)
        try:
            output = await self.run_agent_step(
                run,
                step_key,
                prompt_name,
                artifact,
                allow_interaction=allow_interaction,
                agent_name=agent_name,
                fresh_session=fresh_session,
            )
        except UserInputRequired:
            raise
        decision = self._review_decision(output, config)
        if not decision["passed"]:
            raise WorkflowError(f"{step_key}: review strategy {mode} failed: {decision['reason']}")

    async def ai_implementation_review_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "02_implementation_review.md",
        artifact: str = "implementation-review.md",
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
    ) -> None:
        """Run AI implementation review, then compile task files from AI-authored todo.md."""
        output_dir = Path(run["workspace"]) / "output"
        await self.review_step(
            run,
            "implementation_review",
            prompt_name,
            artifact,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
        todo = read_text(output_dir / "todo.md")
        if not todo.strip():
            raise WorkflowError("implementation_review: todo.md is missing or empty; Plan Tasks must be produced by AI first.")
        if "TASK-001" not in todo:
            raise WorkflowError("implementation_review: AI-authored todo.md must include at least TASK-001.")
        manifest = self._render_task_manifest(todo)
        write_text(output_dir / "task-manifest.md", manifest)
        tasks = self._task_entries_from_manifest(manifest)
        write_text(
            output_dir / "task-manifest.json",
            json.dumps({"source": "ai-authored todo.md", "tasks": tasks}, indent=2, ensure_ascii=False),
        )
        self._write_task_todo_files(output_dir, todo, manifest)
        await self.log(run, f"implementation_review: AI review passed; compiled {len(tasks)} task manifest entrie(s) from todo.md")
        await self.refresh_artifacts(run["id"])

    async def final_review_step(self, run: dict[str, Any], artifact: str = "final-review.md") -> None:
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        try:
            await self.functions.call_python_function(
                self._run_with_step_context(run, {"key": "final_review"}),
                "validate_general_auto_final",
                output_dir,
                artifact,
            )
        except WorkflowError:
            raise
        await self.refresh_artifacts(run["id"])

    async def prepare_project_step(self, run: dict[str, Any], prompt_name: str = "00_prepare.md", artifact: str = "architecture.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        architecture_path = project_dir / "architecture.md"
        artifact = normalize_artifact_name(artifact)
        output_dir = Path(run["workspace"]) / "output"
        project_index = render_project_index_markdown(project_dir)
        write_text(output_dir / "project-index.md", project_index)
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        instructions = orchestrator.extract_user_instructions(requirement, project_dir)
        architecture_contract = orchestrator.build_architecture_contract(project_dir, project_index, instructions)
        write_text(output_dir / "architecture-contract.json", json.dumps(architecture_contract, indent=2, ensure_ascii=False))
        await self._ensure_project_agent_configs(run, project_dir)

        # Deprecated compatibility step.  Current controller workflows should not
        # call this step: project understanding belongs to Qwen/OpenCode, while
        # the platform only provides a small project index/profile as prompt
        # context.  Keep a lightweight artifact for legacy workflows that still
        # reference prepare_project, but do not write architecture.md into the
        # user's project.
        rendered = self.render_project_architecture_markdown(run, project_dir)
        write_text(output_dir / artifact, rendered)
        await self.refresh_artifacts(run["id"])
        await self.log(run, "prepare_project: wrote legacy context artifact only; project files were not modified")

    @staticmethod
    def render_project_architecture_markdown(run: dict[str, Any], project_dir: Path) -> str:
        requirement = read_text(Path(run["workspace"]) / "requirement.md").strip()
        profile = project_profile(project_dir)
        overview = project_overview(project_dir, limit=60)
        qwen_settings = "present" if (project_dir / ".qwen" / "settings.json").is_file() else "missing"
        opencode_settings = "present" if (project_dir / "opencode.json").is_file() else "missing"
        return (
            "# Architecture\n\n"
            "## Project Summary\n"
            "- Current purpose: Existing project inferred from current files.\n"
            f"- User request: {requirement or 'Complete the requested workflow task.'}\n\n"
            "## Runtime Agent Settings\n"
            f"- Qwen project settings: {qwen_settings} at `.qwen/settings.json`\n"
            f"- OpenCode project settings: {opencode_settings} at `opencode.json`\n"
            "- Rule: agent read access may use project settings, but generated edits must remain inside the selected Project path.\n\n"
            "## Detected Stack\n"
            f"{profile}\n\n"
            "## Current Structure\n"
            f"{overview}\n\n"
            "## Implementation Rules\n"
            "- Follow the existing language and structure.\n"
            "- Keep changes small and easy to review.\n"
            "- Keep production code and tests separate.\n"
            "- Do not edit files outside the selected Project path.\n"
            "- Do not skip the external validation script.\n"
        )

    async def run_tests(self, run: dict[str, Any]) -> None:
        try:
            await PYTHON_FUNCTIONS["run_pytest"](self.functions.context(run))
        except WorkflowFunctionError as exc:
            raise WorkflowError(str(exc)) from exc

    async def generate_tests_step(self, run: dict[str, Any], prompt_name: str = "07_test.md", artifact: str = "test-plan.md", *, agent_name: str | None = None) -> None:
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        project_dir = Path(run.get("project_path") or ROOT)
        await self._ensure_project_agent_configs(run, project_dir)

        before = project_file_snapshot(project_dir)
        attempt_snapshot = project_content_snapshot(project_dir)
        try:
            await self.run_agent_step(
                run,
                "generate_tests",
                prompt_name,
                artifact,
                agent_name=agent_name,
                fresh_session=self._fresh_session_for_step(run, "generate_tests"),
            )
        except Exception as exc:
            await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, "generate_tests", exc)
            raise

        try:
            direct_files = self._direct_edit_files_from_snapshot(
                project_dir,
                before,
                project_file_snapshot(project_dir),
                require_test_files=True,
            )
            if not direct_files:
                direct_files = self._apply_file_blocks_for_direct_edit(
                    project_dir,
                    read_text(output_dir / artifact),
                    run=run,
                    step_key="generate_tests",
                    require_test_files=True,
                    validation_script=run.get("validation_script"),
                    fallback_scripts=self._fallback_validation_scripts(run),
                    output_label="agent generate_tests file block direct edit",
                )
            if not direct_files:
                direct_files = self._existing_project_test_files(project_dir)
            if not direct_files:
                raise WorkflowError(
                    f"generate_tests did not directly create or modify pytest files under {project_dir / 'tests'}. "
                    "Use Qwen/OpenCode file edit/write tools to directly create project-specific tests under tests/."
                )

            validate_generated_test_files(direct_files)
        except Exception as exc:
            await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, "generate_tests", exc)
            raise

        summary = self._render_direct_edit_summary(
            "Generated Tests Direct Edit Result",
            "GENERATE-TESTS",
            "Create focused automated tests",
            direct_files,
        )
        write_text(output_dir / artifact, summary)
        self._write_task_direct_state(output_dir, project_dir, "GENERATE-TESTS", "generate_tests", direct_files)
        await self.log(run, "generate_tests: accepted project test file(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
        await self.refresh_artifacts(run["id"])

    @staticmethod
    def _existing_project_test_files(project_dir: Path) -> list[tuple[str, str]]:
        tests_dir = project_dir / "tests"
        if not tests_dir.is_dir():
            return []
        files: list[tuple[str, str]] = []
        for path in sorted(tests_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".py":
                continue
            try:
                rel_path = path.relative_to(project_dir).as_posix()
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            files.append((rel_path, content.rstrip("\n") + "\n"))
        return files

    async def build_step(self, run: dict[str, Any], prompt_name: str = "05_build.md", artifact: str = "build-result.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        await self._ensure_project_agent_configs(run, project_dir)
        before = project_file_snapshot(project_dir)
        build_config = self._config_for_step(run, "build")
        allow_test_files_in_task_loop = bool_config(build_config, "allowTestFilesInTaskLoop", False)

        if self._is_auto_development_workflow(run) and bool_config(build_config, "enableTaskLoop", False):
            manifest_json_path = output_dir / "task-manifest.json"
            tasks: list[dict[str, Any]] = []
            if manifest_json_path.is_file():
                try:
                    parsed = json.loads(read_text(manifest_json_path))
                    raw_tasks = parsed.get("tasks") if isinstance(parsed, dict) else []
                    if isinstance(raw_tasks, list):
                        tasks = [task for task in raw_tasks if isinstance(task, dict)]
                except json.JSONDecodeError:
                    tasks = []
            if not tasks:
                manifest = read_text(output_dir / "task-manifest.md") or read_text(output_dir / "todo.md")
                tasks = self._task_entries_from_manifest(manifest, owner="build")
            if not tasks:
                tasks = [{"id": "TASK-001", "owner": "build", "title": "Full requested production change"}]
            build_feedback = self._build_step_feedback(run)
            generic_build_feedback = self._feedback_is_generic_for_task_loop(build_feedback)
            if generic_build_feedback:
                tasks = self._with_generic_repair_task(tasks, owner="build")
            total = len(tasks)
            task_artifacts: list[tuple[str, str, str]] = []
            any_task_changed = False

            for index, task in enumerate(tasks, start=1):
                task_id = str(task.get("id") or f"TASK-{index:03d}")
                task_title = str(task.get("title") or task_id)
                task_artifact = self._task_output_artifact(task_id, "build-result.md")
                task_artifact_path = output_dir / task_artifact
                task_artifact_path.parent.mkdir(parents=True, exist_ok=True)
                task_has_feedback = self._latest_feedback_mentions_task(
                    build_feedback,
                    task_id,
                ) or (generic_build_feedback and bool(task.get("_generic_repair_task")))
                if (
                    task_artifact_path.is_file()
                    and not task_has_feedback
                    and (
                        self._task_direct_state_is_satisfied(output_dir, project_dir, task_id, "build")
                        or (self._file_blocks_allowed_as_direct_edits(run, "build") and self._task_artifact_is_satisfied(project_dir, task_artifact_path))
                    )
                ):
                    task_result = read_text(task_artifact_path)
                    task_artifacts.append((task_id, task_title, task_result))
                    await self.log(run, f"build/{task_id}: skipped because direct edits from this task are already present and preserved")
                    continue

                scoped_run = self._task_run(run, task, index=index, total=total, phase="build")
                task_before = project_file_snapshot(project_dir)
                attempt_snapshot = project_content_snapshot(project_dir)
                await self.log(run, f"build: task loop {index}/{total} {task_id} - {task_title}")
                try:
                    await self.run_agent_step(
                        scoped_run,
                        "build",
                        prompt_name,
                        task_artifact,
                        agent_name=agent_name,
                        fresh_session=self._fresh_session_for_step(run, "build"),
                    )

                    direct_files = self._direct_edit_files_from_snapshot(
                        project_dir,
                        task_before,
                        project_file_snapshot(project_dir),
                        forbid_test_files=not allow_test_files_in_task_loop,
                    )
                    if not direct_files:
                        direct_files = self._apply_file_blocks_for_direct_edit(
                            project_dir,
                            read_text(task_artifact_path),
                            run=run,
                            step_key="build",
                            forbid_test_files=not allow_test_files_in_task_loop,
                            validation_script=run.get("validation_script"),
                            fallback_scripts=self._fallback_validation_scripts(run),
                            output_label=f"agent build task {task_id} file block direct edit",
                        )
                    if not direct_files:
                        raise WorkflowError(
                            f"build task {task_id} did not directly create or modify project files under Project Path: {project_dir}. "
                            "Use Qwen/OpenCode file edit/write tools to directly modify required files inside Project Path."
                        )

                    if not allow_test_files_in_task_loop:
                        validate_build_files_are_not_tests(direct_files)
                    self._validate_build_direct_files_are_substantive(run, direct_files)
                    validate_build_files_do_not_overwrite_validation_scripts(
                        project_dir,
                        direct_files,
                        validation_script=run.get("validation_script"),
                        fallback_scripts=self._fallback_validation_scripts(run),
                    )
                    validate_generated_code_files_are_clean(direct_files)
                    self._write_task_direct_state(output_dir, project_dir, task_id, "build", direct_files)
                    self._validate_previous_direct_task_states_preserved(
                        output_dir,
                        project_dir,
                        current_index=index,
                        current_task_id=task_id,
                        phase="build",
                    )
                except Exception as exc:
                    await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, f"build/{task_id}", exc)
                    if isinstance(exc, UserInputRequired):
                        raise
                    raise WorkflowError(f"{task_id}: {exc}") from exc
                task_result = self._render_direct_edit_summary("Build Direct Edit Result", task_id, task_title, direct_files)
                write_text(task_artifact_path, task_result)
                task_artifacts.append((task_id, task_title, task_result))
                any_task_changed = True
                await self.log(run, f"build/{task_id}: accepted direct agent production edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
                if await self._external_validation_passes_now(run, output_dir):
                    break

            aggregate = self._render_aggregated_task_outputs("Build Result", task_artifacts)
            write_text(output_dir / artifact, aggregate)
            await self.refresh_artifacts(run["id"])
            after = project_file_snapshot(project_dir)
            if not snapshot_changed(before, after) and not task_artifacts and not any_task_changed:
                raise WorkflowError(
                    f"build did not directly create or modify project files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools to directly modify files inside Project Path."
                )
            return

        attempt_snapshot = project_content_snapshot(project_dir)
        try:
            await self.run_agent_step(
                run,
                "build",
                prompt_name,
                artifact,
                agent_name=agent_name,
                fresh_session=self._fresh_session_for_step(run, "build"),
            )

            direct_files = self._direct_edit_files_from_snapshot(
                project_dir,
                before,
                project_file_snapshot(project_dir),
                forbid_test_files=True,
            )
            if not direct_files:
                direct_files = self._apply_file_blocks_for_direct_edit(
                    project_dir,
                    read_text(output_dir / artifact),
                    run=run,
                    step_key="build",
                    forbid_test_files=True,
                    validation_script=run.get("validation_script"),
                    fallback_scripts=self._fallback_validation_scripts(run),
                    output_label="agent build file block direct edit",
                )
            if not direct_files:
                raise WorkflowError(
                    f"build did not directly create or modify project files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools to directly modify files inside Project Path."
                )
            validate_build_files_are_not_tests(direct_files)
            self._validate_build_direct_files_are_substantive(run, direct_files)
            validate_build_files_do_not_overwrite_validation_scripts(
                project_dir,
                direct_files,
                validation_script=run.get("validation_script"),
                fallback_scripts=self._fallback_validation_scripts(run),
            )
            validate_generated_code_files_are_clean(direct_files)
        except Exception as exc:
            await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, "build", exc)
            raise
        summary = self._render_direct_edit_summary("Build Direct Edit Result", "BUILD", "Production changes", direct_files)
        write_text(output_dir / artifact, summary)
        self._write_task_direct_state(output_dir, project_dir, "BUILD", "build", direct_files)
        await self.log(run, "build: accepted direct agent production edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
        await self.refresh_artifacts(run["id"])


    @staticmethod
    def _render_architecture_delta(task_id: str, task_title: str, direct_files: list[tuple[str, str]], output_dir: Path) -> str:
        contract = read_text(output_dir / "architecture-contract.md")
        files = [str(rel_path).replace("\\", "/") for rel_path, _ in direct_files]
        existing_roots = []
        for rel_path in files:
            first = rel_path.split("/", 1)[0] if rel_path else ""
            if first and first not in existing_roots:
                existing_roots.append(first)
        risk = "low"
        if any(first in {"workflow_runtime", "runner", "services", "frontend", "backend"} for first in existing_roots):
            risk = "medium"
        if any(rel_path.startswith(('../', '/', '.git/', '.ai-workflow/', '.qwen-workflow/')) for rel_path in files):
            risk = "high"
        lines = [
            "# Architecture Delta Summary",
            "",
            "Status: READY",
            "",
            "## Task",
            f"- ID: {task_id}",
            f"- Title: {task_title}",
            "",
            "## Changed Files",
        ]
        lines.extend(f"- `{rel_path}`" for rel_path in files)
        lines.extend([
            "",
            "## Architecture Alignment",
            f"- Existing roots touched: {', '.join(existing_roots) if existing_roots else 'None'}",
            "- Contract applied: output/architecture-contract.md" if contract.strip() else "- Contract applied: no explicit contract artifact was available",
            f"- Architecture drift risk: {risk}",
            "",
            "## Follow-up Review",
            "- AI review should confirm that changed files reuse existing modules and do not introduce parallel architecture.",
            "- If this task added a new root or duplicate subsystem, retry the current task and fold the change into the existing extension point.",
        ])
        return "\n".join(lines).rstrip() + "\n"

    def _append_workflow_decision(
        self,
        output_dir: Path,
        *,
        task_id: str,
        task_title: str,
        status: str,
        next_action: str,
        reason: str,
        changed_files: list[tuple[str, str]] | None = None,
    ) -> None:
        log_path = output_dir / "workflow-decision-log.md"
        existing = read_text(log_path).rstrip() if log_path.is_file() else "# Adaptive Workflow Decision Log\n\n"
        files = [rel_path for rel_path, _ in (changed_files or [])]
        file_line = ", ".join(files) if files else "None"
        entry = [
            "",
            f"## {task_id} - {task_title}",
            f"- Status: {status}",
            f"- Next action: {next_action}",
            f"- Reason: {reason}",
            f"- Changed files: {file_line}",
            "",
        ]
        write_text(log_path, existing + "\n" + "\n".join(entry))

    @staticmethod
    def _project_has_test_files(project_dir: Path) -> bool:
        return any(rel_path.replace("\\", "/").startswith("tests/test_") for rel_path in project_file_snapshot(project_dir))

    def _has_configured_validation_script(self, run: dict[str, Any], project_dir: Path) -> bool:
        if str(run.get("validation_script") or "").strip():
            return True
        for name in self._fallback_validation_scripts(run):
            if (project_dir / str(name)).is_file():
                return True
        return False

    @staticmethod
    def _project_text_evidence(project_dir: Path, *, max_files: int = 260, max_chars_per_file: int = 12000) -> str:
        chunks: list[str] = []
        for rel_path in sorted(project_file_snapshot(project_dir))[:max_files]:
            suffix = Path(rel_path).suffix.lower()
            if suffix not in {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs", ".md", ".txt", ".yaml", ".yml", ".json"}:
                continue
            try:
                chunks.append((project_dir / rel_path).read_text(encoding="utf-8")[:max_chars_per_file])
            except (UnicodeDecodeError, OSError):
                continue
        return "\n".join(chunks)
