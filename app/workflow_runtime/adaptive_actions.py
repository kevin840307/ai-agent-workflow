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


class AdaptiveWorkflowActionsMixin:
    async def generate_task_prompts_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "00_generate_task_prompts.md",
        artifact: str = "task-manifest.md",
        *,
        agent_name: str | None = None,
    ) -> None:
        """Ask the agent to author Adaptive task prompts, then validate and materialize prompt files."""
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        output = await self.run_agent_step(
            run,
            "generate_task_prompts",
            prompt_name,
            artifact,
            agent_name=agent_name,
            fresh_session=self._fresh_session_for_step(run, "generate_task_prompts"),
        )
        manifest = self._parse_ai_task_prompt_manifest(output, step_key="generate_task_prompts")
        tasks = manifest.get("tasks") or []
        self._current_project_dir = Path(run.get("project_path") or ROOT)
        self._write_ai_task_prompt_manifest(output_dir, manifest, source_label="AI-generated Adaptive execution prompts")
        await self.refresh_artifacts(run["id"])
        await self.log(run, f"generate_task_prompts: AI generated {len(tasks)} task prompt(s)")

    @staticmethod
    def _extract_first_json_object(text: str) -> dict[str, Any]:
        value = (text or "").strip()
        if not value:
            raise WorkflowError("AI task prompt manifest is empty.")
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", value, flags=re.DOTALL | re.IGNORECASE)
        if fence:
            value = fence.group(1).strip()
        else:
            start = value.find("{")
            end = value.rfind("}")
            if start >= 0 and end > start:
                value = value[start : end + 1]
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowError("AI task planner must output a valid JSON object with a tasks array.") from exc
        if not isinstance(parsed, dict):
            raise WorkflowError("generate_task_prompts: AI manifest must be a JSON object.")
        return parsed

    def _parse_ai_task_prompt_manifest(self, output: str, *, step_key: str = "generate_task_prompts") -> dict[str, Any]:
        raw = self._extract_first_json_object(output)
        raw_tasks = raw.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise WorkflowError(f"{step_key}: AI manifest must contain a non-empty `tasks` array.")
        tasks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(raw_tasks, start=1):
            if not isinstance(item, dict):
                raise WorkflowError(f"{step_key}: tasks[{index}] must be an object.")
            task_id = str(item.get("id") or f"TASK-{index:03d}").strip().upper()
            if not re.fullmatch(r"TASK-\d{3}", task_id):
                task_id = f"TASK-{index:03d}"
            if task_id in seen:
                raise WorkflowError(f"{step_key}: duplicate task id {task_id}.")
            seen.add(task_id)
            title = str(item.get("title") or item.get("name") or task_id).strip()[:160] or task_id
            prompt = str(item.get("prompt") or item.get("instruction") or item.get("task_prompt") or "").strip()
            if len(prompt) < 20:
                raise WorkflowError(f"{step_key}: {task_id} must include a concrete `prompt` string.")
            self._validate_ai_task_prompt_quality(task_id, prompt, step_key=step_key)
            acceptance = item.get("acceptance") or item.get("acceptance_criteria") or []
            if isinstance(acceptance, str):
                acceptance_items = [line.strip(" -") for line in acceptance.splitlines() if line.strip()]
            elif isinstance(acceptance, list):
                acceptance_items = [str(line).strip() for line in acceptance if str(line).strip()]
            else:
                acceptance_items = []
            tasks.append(
                {
                    "id": task_id,
                    "title": title,
                    "prompt": prompt,
                    "acceptance": acceptance_items,
                    "kind": str(item.get("kind") or item.get("owner") or "implementation").strip() or "implementation",
                }
            )
        spec = str(
            raw.get("spec")
            or raw.get("spec_markdown")
            or raw.get("acceptance_spec")
            or raw.get("review_spec")
            or ""
        ).strip()
        if len(spec) < 40:
            raise WorkflowError(f"{step_key}: AI manifest must include a non-empty Markdown `spec` string for review.")
        return {
            "status": "READY",
            "source": "ai-generated",
            "goal": str(raw.get("goal") or raw.get("summary") or "").strip(),
            "spec": spec,
            "tasks": tasks,
        }


    @staticmethod
    def _validate_ai_task_prompt_quality(task_id: str, prompt: str, *, step_key: str = "generate_task_prompts") -> None:
        """Keep AI-generated task prompts as human CLI instructions, not shell scripts.

        The adaptive workflow is meant to simulate a human giving concise prompts
        to Qwen/OpenCode.  If the planner emits shell commands or inline source
        code, the execution step becomes brittle and often bypasses the agent's
        normal edit tools.
        """
        text = (prompt or "").strip()
        lowered = text.lower()
        if re.match(r"^\s*(mkdir|md|echo|copy|xcopy|move|del|erase|type|cat|printf|powershell|pwsh|cmd|touch)\b", text, flags=re.I):
            raise WorkflowError(
                f"{step_key}: {task_id} prompt must be a concise natural-language CLI instruction, not a shell command."
            )
        if re.search(r"[A-Za-z]:[\\/]", text):
            raise WorkflowError(
                f"{step_key}: {task_id} prompt must not contain absolute paths; Project Path is supplied by the workflow."
            )
        if re.search(r"(^|\s)(>>?|2>|1>)\s*\S+", text):
            raise WorkflowError(
                f"{step_key}: {task_id} prompt must not use shell redirection; ask the CLI agent to edit files directly."
            )
        if "```" in text:
            raise WorkflowError(
                f"{step_key}: {task_id} prompt must not contain code fences; keep it as an instruction."
            )
        if len(text) > 1400:
            raise WorkflowError(
                f"{step_key}: {task_id} prompt is too long; keep task prompts short and concrete."
            )
        code_markers = ["def ", "class ", "import ", "return ", "function ", "public ", "private "]
        if sum(1 for marker in code_markers if marker in lowered) >= 3:
            raise WorkflowError(
                f"{step_key}: {task_id} prompt looks like source code; output a human instruction instead."
            )

    def _write_ai_task_prompt_manifest(self, output_dir: Path, manifest: dict[str, Any], *, source_label: str = "AI-generated task prompts") -> None:
        task_prompt_dir = output_dir / "task-prompts"
        todo_dir = output_dir / "todos"
        task_prompt_dir.mkdir(parents=True, exist_ok=True)
        todo_dir.mkdir(parents=True, exist_ok=True)
        tasks = [task for task in manifest.get("tasks") or [] if isinstance(task, dict)]
        canonical_manifest = dict(manifest)
        canonical_manifest.setdefault("status", "READY")
        canonical_manifest.setdefault("schema_version", 1)
        canonical_manifest["tasks"] = tasks
        spec = str(canonical_manifest.get("spec") or "").strip()
        write_text(output_dir / "spec.md", spec.rstrip() + "\n")
        write_text(output_dir / "task-manifest.json", json.dumps(canonical_manifest, indent=2, ensure_ascii=False))
        project_dir = Path(getattr(self, "_current_project_dir", "") or ".")
        try:
            # Compile a deterministic workflow-instance artifact from the AI task manifest.
            # The runner still executes only built-in steps; this artifact documents and validates
            # the internal task loop that Python is allowed to run.
            workflow_instance = orchestrator.compile_workflow_instance(canonical_manifest, run_profile="normal")
            task_findings = orchestrator.validate_task_manifest(canonical_manifest, project_dir)
            workflow_findings = orchestrator.validate_workflow_instance(workflow_instance, canonical_manifest)
            write_text(output_dir / "generated-workflow-instance.json", json.dumps(workflow_instance, indent=2, ensure_ascii=False))
            write_text(output_dir / "workflow-instance-validation.md", orchestrator.render_validation_markdown(task_findings, workflow_findings))
            write_text(output_dir / "workflow-run-trace.md", orchestrator.render_run_trace(workflow_instance))
        except Exception as exc:
            write_text(output_dir / "generated-workflow-instance.json", json.dumps({"status": "FAIL", "error": str(exc)}, indent=2, ensure_ascii=False))
            write_text(output_dir / "workflow-instance-validation.md", f"# Workflow Instance Validation\n\nStatus: FAIL\n\n- {exc}\n")
        lines = ["# Task Manifest", "", "Status: READY", "", f"Source: {source_label}.", "", "## SPEC", "", "See `output/spec.md`.", "", "## Small Task Order", "", "## Task Prompt Order"]
        todo_lines = ["# Todo", "", "Status: READY", "", "## Task Index", "", "| ID | Task | Kind | Acceptance Criteria |", "| --- | --- | --- | --- |"]
        index_lines = ["# Task Todo Index", "", "Status: READY", ""]
        for index, task in enumerate(tasks, start=1):
            task_id = str(task.get("id") or f"TASK-{index:03d}")
            title = str(task.get("title") or task_id)
            kind = str(task.get("kind") or "implementation")
            lines.append(f"{index}. {task_id} [kind={kind}]: {title}")
            prompt_text = str(task.get("prompt") or "").strip()
            acceptance = task.get("acceptance") or []
            acceptance_lines = "\n".join(f"- {item}" for item in acceptance) if acceptance else "- Complete the current task and keep the project runnable."
            acceptance_cell = "; ".join(str(item) for item in acceptance) if acceptance else "Complete the current task and keep the project runnable."
            todo_lines.append(f"| {task_id} | {title} | {kind} | {acceptance_cell} |")
            task_doc = "\n".join(
                [
                    f"# {task_id}: {title}",
                    "",
                    "Status: READY",
                    "",
                    "## AI-Generated Prompt",
                    prompt_text,
                    "",
                    "## Acceptance",
                    acceptance_lines,
                    "",
                ]
            )
            safe_id = self._safe_task_id(task_id)
            write_text(task_prompt_dir / f"{safe_id}.md", task_doc)
            write_text(todo_dir / f"{safe_id}.md", task_doc)
            index_lines.append(f"- output/todos/{safe_id}.md")
        write_text(output_dir / "task-manifest.md", "\n".join(lines).rstrip() + "\n")
        write_text(output_dir / "todo.md", "\n".join(todo_lines).rstrip() + "\n")
        write_text(todo_dir / "INDEX.md", "\n".join(index_lines).rstrip() + "\n")

    async def adaptive_review_and_validation_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "01_ai_review.md",
        artifact: str = "ai-review.md",
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
    ) -> None:
        """Run final AI review and then the Python gate when validation/tests exist."""
        output_dir = Path(run["workspace"]) / "output"
        await self.review_step(
            run,
            "ai_review",
            prompt_name,
            artifact,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
        await self.functions.call_python_function(
            self._run_with_step_context(run, {"key": "ai_review", "config": self._config_for_step(run, "ai_review")}),
            "adaptive_python_gate",
            output_dir,
            "external-validation-result.md",
        )
        await self.refresh_artifacts(run["id"])

    async def _external_validation_passes_now(self, run: dict[str, Any], output_dir: Path) -> bool:
        if not str(run.get("validation_script") or "").strip():
            return False
        try:
            await self.functions.call_python_function(run, "run_external_validation", output_dir, "external-validation-result.md")
            await self.refresh_artifacts(run["id"])
            await self.log(run, "external_validation: passed early; remaining task loop items can be skipped")
            return True
        except Exception as exc:
            await self.log(run, f"external_validation: not passing yet after current task: {str(exc)[:500]}")
            return False

    async def adaptive_generation_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "00_auto_generation.md",
        artifact: str = "auto-generation-result.md",
        *,
        agent_name: str | None = None,
    ) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        await self._ensure_project_agent_configs(run, project_dir)
        before = project_file_snapshot(project_dir)

        if self._is_adaptive_workflow(run) and bool_config(self._config_for_step(run, "auto_generation"), "enableTaskLoop", False):
            manifest_path = output_dir / "task-manifest.json"
            manifest: dict[str, Any] = {}
            tasks: list[dict[str, Any]] = []
            if manifest_path.is_file():
                try:
                    parsed = json.loads(read_text(manifest_path))
                    manifest = parsed if isinstance(parsed, dict) else {}
                    raw_tasks = manifest.get("tasks") if isinstance(manifest, dict) else []
                    if isinstance(raw_tasks, list):
                        tasks = [task for task in raw_tasks if isinstance(task, dict)]
                except json.JSONDecodeError:
                    manifest = {}
                    tasks = []
            if not tasks:
                raise WorkflowError("auto_generation: task-manifest.json has no AI-generated tasks. Retry Generate Task Prompts.")

            task_artifacts: list[tuple[str, str, str]] = []
            generation_feedback = failure_feedback_for_step(read_text(Path(run["workspace"]) / "input" / "failure-feedback.md"), "auto_generation")
            generic_generation_feedback = self._feedback_is_generic_for_task_loop(generation_feedback)
            if generic_generation_feedback:
                tasks = self._with_generic_repair_task(tasks, owner="build")
            total = len(tasks)
            for index, task in enumerate(tasks, start=1):
                task_id = str(task.get("id") or f"TASK-{index:03d}")
                task_title = str(task.get("title") or task_id)
                task_artifact = self._task_output_artifact(task_id, "adaptive-generation-result.md")
                task_artifact_path = output_dir / task_artifact
                task_artifact_path.parent.mkdir(parents=True, exist_ok=True)
                task_has_feedback = self._latest_feedback_mentions_task(
                    generation_feedback,
                    task_id,
                ) or (generic_generation_feedback and bool(task.get("_generic_repair_task")))
                if (
                    task_artifact_path.is_file()
                    and not task_has_feedback
                    and (
                        self._task_direct_state_is_satisfied(output_dir, project_dir, task_id, "auto_generation")
                        or (self._file_blocks_allowed_as_direct_edits(run, "auto_generation") and self._task_artifact_is_satisfied(project_dir, task_artifact_path))
                    )
                ):
                    task_result = read_text(task_artifact_path)
                    task_artifacts.append((task_id, task_title, task_result))
                    self._append_workflow_decision(
                        output_dir,
                        task_id=task_id,
                        task_title=task_title,
                        status="pass",
                        next_action="continue",
                        reason="Skipped because direct edits from this completed valid task are already present and preserved.",
                    )
                    await self.log(run, f"auto_generation/{task_id}: skipped because direct edits from this task are already present and preserved")
                    continue

                scoped_run = self._task_run(run, task, index=index, total=total, phase="adaptive_generation")
                task_before = project_file_snapshot(project_dir)
                attempt_snapshot = project_content_snapshot(project_dir)
                await self.log(run, f"auto_generation: adaptive task loop {index}/{total} {task_id} - {task_title}")
                try:
                    await self.run_agent_step(
                        scoped_run,
                        "auto_generation",
                        prompt_name,
                        task_artifact,
                        agent_name=agent_name,
                        fresh_session=self._fresh_session_for_step(run, "auto_generation"),
                    )

                    direct_files = self._direct_edit_files_from_snapshot(
                        project_dir,
                        task_before,
                        project_file_snapshot(project_dir),
                    )
                    if not direct_files:
                        direct_files = self._apply_file_blocks_for_direct_edit(
                            project_dir,
                            read_text(task_artifact_path),
                            run=run,
                            step_key="auto_generation",
                            validation_script=run.get("validation_script"),
                            fallback_scripts=self._fallback_validation_scripts(run),
                            output_label=f"agent adaptive task {task_id} file block direct edit",
                        )
                    if not direct_files:
                        raise WorkflowError(
                            f"auto_generation task {task_id} did not directly create or modify files under Project Path: {project_dir}. "
                            "Use Qwen/OpenCode file edit/write tools to directly modify files inside Project Path."
                        )
                    validate_build_files_do_not_overwrite_validation_scripts(
                        project_dir,
                        direct_files,
                        validation_script=run.get("validation_script"),
                        fallback_scripts=self._fallback_validation_scripts(run),
                    )
                    validate_test_code_is_separate(direct_files)
                    validate_generated_code_files_are_clean(direct_files)
                    validate_generated_test_files(only_test_files(direct_files)) if only_test_files(direct_files) else None
                    self._write_task_direct_state(output_dir, project_dir, task_id, "auto_generation", direct_files)
                    self._validate_previous_direct_task_states_preserved(
                        output_dir,
                        project_dir,
                        current_index=index,
                        current_task_id=task_id,
                        phase="auto_generation",
                    )
                except Exception as exc:
                    self._append_workflow_decision(
                        output_dir,
                        task_id=task_id,
                        task_title=task_title,
                        status="fail",
                        next_action="repair_current_step",
                        reason=str(exc)[:500],
                    )
                    await self.log(run, f"auto_generation/{task_id}: reflection decision=repair_current_step after validation failure")
                    await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, f"auto_generation/{task_id}", exc)
                    if isinstance(exc, UserInputRequired):
                        raise
                    raise WorkflowError(f"{task_id}: {exc}") from exc
                architecture_delta = self._render_architecture_delta(task_id, task_title, direct_files, output_dir)
                write_text(output_dir / self._task_output_artifact(task_id, "architecture-delta.md"), architecture_delta)
                task_result = self._render_direct_edit_summary("Adaptive Generation Direct Edit Result", task_id, task_title, direct_files)
                write_text(task_artifact_path, task_result)
                task_artifacts.append((task_id, task_title, task_result))
                self._append_workflow_decision(
                    output_dir,
                    task_id=task_id,
                    task_title=task_title,
                    status="pass",
                    next_action="continue",
                    reason="Task changed project files and passed local Adaptive validation gates.",
                    changed_files=direct_files,
                )
                await self.log(run, f"auto_generation/{task_id}: accepted direct agent edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
                await self.log(run, f"auto_generation/{task_id}: architecture delta recorded; contract alignment will be checked by review")
                await self.log(run, f"auto_generation/{task_id}: reflection decision=continue after validation passed")
            write_text(output_dir / artifact, self._render_aggregated_task_outputs("Adaptive Generation Result", task_artifacts))
            await self.refresh_artifacts(run["id"])
            after = project_file_snapshot(project_dir)
            if not snapshot_changed(before, after) and not task_artifacts:
                raise WorkflowError(
                    f"auto_generation did not directly create or modify files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools to directly modify files inside Project Path."
                )
            return

        attempt_snapshot = project_content_snapshot(project_dir)
        try:
            await self.run_agent_step(
                run,
                "auto_generation",
                prompt_name,
                artifact,
                agent_name=agent_name,
                fresh_session=self._fresh_session_for_step(run, "auto_generation"),
            )
            direct_files = self._direct_edit_files_from_snapshot(
                project_dir,
                before,
                project_file_snapshot(project_dir),
            )
            if not direct_files:
                direct_files = self._apply_file_blocks_for_direct_edit(
                    project_dir,
                    read_text(output_dir / artifact),
                    run=run,
                    step_key="auto_generation",
                    validation_script=run.get("validation_script"),
                    fallback_scripts=self._fallback_validation_scripts(run),
                    output_label="agent adaptive file block direct edit",
                )
            if not direct_files:
                raise WorkflowError(
                    f"auto_generation did not directly create or modify files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools to directly modify files inside Project Path."
                )
            validate_build_files_do_not_overwrite_validation_scripts(
                project_dir,
                direct_files,
                validation_script=run.get("validation_script"),
                fallback_scripts=self._fallback_validation_scripts(run),
            )
            validate_test_code_is_separate(direct_files)
            validate_generated_code_files_are_clean(direct_files)
        except Exception as exc:
            await self._restore_failed_project_attempt(run, project_dir, attempt_snapshot, "auto_generation", exc)
            raise
        summary = self._render_direct_edit_summary("Adaptive Generation Direct Edit Result", "AUTO-GENERATION", "Adaptive generation", direct_files)
        write_text(output_dir / artifact, summary)
        self._write_task_direct_state(output_dir, project_dir, "AUTO-GENERATION", "auto_generation", direct_files)
        await self.log(run, "auto_generation: accepted direct agent edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
        await self.refresh_artifacts(run["id"])

    async def adaptive_ai_review_with_validation_step(
        self,
        run: dict[str, Any],
        prompt_name: str = "01_ai_review.md",
        artifact: str = "ai-review.md",
        *,
        allow_interaction: bool = False,
        agent_name: str | None = None,
    ) -> None:
        output_dir = Path(run["workspace"]) / "output"
        step_record = next((step for step in run.get("steps", []) if step.get("key") == "ai_review"), {})
        config = {**step_record, **step_config(step_record)}
        if bool_config(config, "runPythonGate", True):
            await self.functions.call_python_functions(
                self._run_with_step_context(run, step_record),
                ["adaptive_python_gate"],
                output_dir,
                "external-validation-result.md",
            )
            await self.refresh_artifacts(run["id"])
            await self.log(run, "ai_review: Python validation/test gate passed or was skipped before AI review")
        await self.review_step(
            run,
            "ai_review",
            prompt_name,
            artifact,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
        await self.log(run, "ai_review: AI review passed after reading validation/test evidence")
