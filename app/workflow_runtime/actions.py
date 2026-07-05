from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.auto_workflow import orchestrator
from app.runtime_modules.errors import UserInputRequired, ValidationError, WorkflowError
from app.runtime_modules.files import (
    apply_build_files,
    failure_feedback_for_step,
    apply_extracted_files,
    extract_build_files,
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
    spec_input_questions,
    split_build_files,
    render_generic_spec_from_requirement,
    render_generic_todo_from_spec,
    build_generic_python_import_smoke_test,
    build_validation_script_pytest_wrapper,
    existing_validation_scripts,
    validate_build_files_do_not_overwrite_validation_scripts,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
    validate_test_code_is_separate,
)
from app.core.paths import ROOT, read_text, write_text
from app.security.workspace_guard import resolve_project_relative_write
from app.security.agent_project_config import ensure_agent_project_configs
from app.workflow_runtime.builtin_functions.registry import PYTHON_FUNCTIONS
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionError
from app.workflow_runtime.task_prompt_generator import TaskPromptGenerator

from .agent_step_runner import AgentStepRunner
from .functions import WorkflowFunctionService
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

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowActions:
    """Step action registry driven by workflow.json.

    Built-in step keys keep their specialized safety behavior, but prompt path,
    artifact name, agent/provider, review strategy, retry, timeout, and function
    settings all come from the persisted workflow step config.
    """

    def __init__(
        self,
        *,
        agent_runner: AgentStepRunner,
        functions: WorkflowFunctionService,
        log: LogFn,
        refresh_artifacts: RefreshArtifactsFn,
    ) -> None:
        self.agent_runner = agent_runner
        self.functions = functions
        self.log = log
        self.refresh_artifacts = refresh_artifacts

    @staticmethod
    def _is_auto_development_workflow(run: dict[str, Any]) -> bool:
        return str(run.get("workflow_id") or "") in {"general-auto-development", "adaptive-auto-workflow"}

    @staticmethod
    def _is_general_auto_development_workflow(run: dict[str, Any]) -> bool:
        return str(run.get("workflow_id") or "") == "general-auto-development"

    @staticmethod
    def _is_adaptive_workflow(run: dict[str, Any]) -> bool:
        return str(run.get("workflow_id") or "") == "adaptive-auto-workflow"

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

    def _file_blocks_allowed_as_direct_edits(self) -> bool:
        return True

    def _apply_file_blocks_for_direct_edit(
        self,
        project_dir: Path,
        output_text: str,
        *,
        require_test_files: bool = False,
        forbid_test_files: bool = False,
        validation_script: str | None = None,
        fallback_scripts: list[str] | None = None,
        output_label: str = "agent file block direct edit output",
    ) -> list[tuple[str, str]]:
        if not self._file_blocks_allowed_as_direct_edits():
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
    ) -> None:
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)

        if self._is_general_auto_development_workflow(run):
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            units = self._requirement_deliverable_units(requirement)
            todo = self._render_fallback_todo(requirement, units)
            write_text(output_dir / artifact, todo)
            await self.refresh_artifacts(run["id"])
            await self.log(run, "plan_tasks: wrote deterministic task plan without agent call")
            return

        try:
            await self.run_agent_step(run, "generate_todo", prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            self.functions.validate_todo(output_dir)
        except UserInputRequired:
            raise
        except (WorkflowError, ValidationError) as exc:
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

    @staticmethod
    def _ordered_task_ids(todo: str) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for match in re.finditer(r"\bTASK-\d{3}\b", todo or ""):
            task_id = match.group(0)
            if task_id not in seen:
                seen.add(task_id)
                ordered.append(task_id)
        return ordered

    @staticmethod
    def _task_title(todo: str, task_id: str) -> str:
        heading = re.search(rf"^###\s+{re.escape(task_id)}\s*:?\s*(.+?)\s*$", todo or "", flags=re.MULTILINE)
        if heading:
            return heading.group(1).strip() or task_id
        table_row = re.search(rf"^\|\s*{re.escape(task_id)}\s*\|\s*([^|]+?)\s*\|", todo or "", flags=re.MULTILINE)
        if table_row:
            return table_row.group(1).strip() or task_id
        return task_id

    def _task_section(self, todo: str, task_id: str) -> str:
        match = re.search(
            rf"^###\s+{re.escape(task_id)}\b.*?(?=^###\s+TASK-\d{{3}}\b|^##\s+|\Z)",
            todo or "",
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(0).strip() if match else ""

    def _task_owner(self, todo: str, task_id: str) -> str:
        title = self._task_title(todo, task_id)
        section = self._task_section(todo, task_id)
        header = title.lower()
        goal_match = re.search(r"(?im)^\s*-\s*goal:\s*(.+)$", section or "")
        goal = goal_match.group(1).lower() if goal_match else ""
        primary = f"{header}\n{goal}"
        text = f"{primary}\n{section}".lower()
        change_pattern = r"\b(implement|create|modify|update|write|add|generate|produce|build)\b"
        if re.search(change_pattern, primary) or re.search(r"(實作|新增|建立|修改|產生|製作)", primary):
            if not re.search(r"\btests?\b", primary) and "測試" not in primary:
                return "build"
        if re.search(r"\b(generate|create|write|add)\s+(focused\s+)?(automated\s+)?tests?\b", primary) or "test files only" in text:
            return "generate_tests"
        if "external validation" in primary and not re.search(r"\b(implement|create|modify|update|write|add|build)\b", primary):
            return "run_external_validation"
        if re.search(r"\b(review|analyze|analyse|inspect|scan|understand|plan)\b", primary) and not re.search(change_pattern, primary):
            return "planning"
        return "build"

    @staticmethod
    def _fallback_validation_scripts(run: dict[str, Any]) -> list[str]:
        for step in run.get("steps") or []:
            if step.get("key") not in {"run_external_validation", "python_gate"}:
                continue
            config = {**step, **step_config(step)}
            value = config.get("fallbackValidationScripts") or config.get("fallback_validation_scripts") or []
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _todo_owned_validation_targets(run: dict[str, Any], todo: str) -> list[str]:
        project_dir = Path(run.get("project_path") or ".").expanduser().resolve()
        protected = existing_validation_scripts(
            project_dir,
            run.get("validation_script"),
            WorkflowActions._fallback_validation_scripts(run),
        )
        if not protected:
            return []
        task_context = todo.split("## External Validation", 1)[0]
        found: list[str] = []
        for script in sorted(protected):
            try:
                display = script.relative_to(project_dir).as_posix()
            except ValueError:
                display = str(script)
            escaped_display = re.escape(display).replace("/", r"[\\/]")
            escaped_name = re.escape(script.name)
            if re.search(rf"(?im)(^|\s|`)(?:{escaped_display}|{escaped_name})(`|\s|$)", task_context):
                found.append(display)
        return found


    @staticmethod
    def _normalize_deliverable_unit(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" -:：。.;；,，、+/\t")
        if not text:
            return ""
        # Remove request framing from the first extracted unit without assuming a domain.
        prefixes = [
            r"^(?:請|麻煩|幫我|協助)(?:你)?\s*",
            r"^用[^,，、+;；]{1,40}?(?:幫我)?(?:建立|製作|產生|實作|新增|寫|撰寫|create|build|implement|write|generate)\s*",
            r"^(?:建立|製作|產生|實作|新增|寫|撰寫)\s*",
            r"^(?:create|build|implement|write|generate|add)\s+(?:a|an|the)?\s*",
        ]
        changed = True
        while changed:
            changed = False
            for pattern in prefixes:
                next_text = re.sub(pattern, "", text, flags=re.I).strip()
                if next_text != text:
                    text = next_text
                    changed = True
        text = re.sub(r"(?:等等|等)$", "", text).strip(" -:：。.;；,，、+/\t")
        return text[:120]

    @classmethod
    def _requirement_deliverable_units(cls, requirement: str) -> list[str]:
        text = str(requirement or "").strip()
        if not text:
            return []
        candidates: list[str] = []
        for line in text.splitlines():
            match = re.match(r"^\s*(?:[-*]|\d+[\.、\)])\s+(.{2,})$", line)
            if match:
                candidates.append(match.group(1))
        if len(candidates) < 2:
            # Split only on explicit list separators. This keeps ordinary prose intact
            # while handling requirements that enumerate independent deliverables.
            raw_parts = re.split(r"\s*(?:\+|、|，|,|；|;|/|和|與|及|\band\b)\s*", text, flags=re.I)
            if len(raw_parts) >= 3:
                candidates = raw_parts
        units: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            unit = cls._normalize_deliverable_unit(item)
            if len(unit) < 2:
                continue
            key = unit.lower()
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)
        if len(units) >= 4 and all(len(unit) <= 40 for unit in units):
            return ["all requested deliverables: " + ", ".join(units)]
        return units[:20]

    def _build_task_ids(self, todo: str) -> list[str]:
        return [task_id for task_id in self._ordered_task_ids(todo) if self._task_owner(todo, task_id) == "build"]

    def _under_split_findings(self, requirement: str, todo: str) -> tuple[list[str], list[str]]:
        units = self._requirement_deliverable_units(requirement)
        if len(units) < 3:
            return [], units
        build_task_ids = self._build_task_ids(todo)
        grouped = len(units) == 1 and units[0].startswith("all requested deliverables: ")
        expected = 1 if grouped else min(len(units), 12)
        task_texts = [f"{self._task_title(todo, task_id)}\n{self._task_section(todo, task_id)}".lower() for task_id in build_task_ids]
        covered_units = 0
        for unit in units:
            unit_key = unit.lower()
            if any(unit_key in task_text for task_text in task_texts):
                covered_units += 1
        findings: list[str] = []
        if len(build_task_ids) < expected or covered_units < expected:
            findings.append(
                "Todo appears under-split: requirement lists "
                f"{len(units)} independently verifiable item(s), but the plan has "
                f"{len(build_task_ids)} build-owned task(s) and explicitly covers {covered_units}. "
                "Create one build task per item or document a grouping reason when grouping is necessary."
            )
        return findings, units

    def _render_fallback_todo(self, requirement: str, deliverable_units: list[str]) -> str:
        units = deliverable_units[:12]
        if not units:
            units = ["production change"]
        multiple = len(units) > 1
        lines = [
            "# Todo",
            "",
            "Status: READY",
            "",
            "## Requirement",
            f"- {requirement or 'Complete the requested change.'}",
            "",
            "## Task Index",
            "| ID | Task | Acceptance Criteria | Depends On |",
            "| --- | --- | --- | --- |",
        ]
        previous = "None"
        for index, unit in enumerate(units, start=1):
            task_id = f"TASK-{index:03d}"
            ac_id = f"AC-{index:03d}"
            title = f"Implement {unit}" if unit != "production change" else "Implement production change"
            lines.append(f"| {task_id} | {title} | {ac_id} | {previous} |")
            previous = task_id
        assembly_id = f"TASK-{len(units) + 1:03d}" if multiple else ""
        if multiple:
            lines.append(f"| {assembly_id} | Assemble and expose the complete requested behavior | AC-{len(units) + 1:03d} | {previous} |")
        lines.extend([
            "",
            "## Task Assembly Plan",
            "- Build order: implement each independently verifiable item first, then assemble them into the final requested behavior.",
            "- Integration point: shared project source files under the selected Project path.",
            "- Assembled behavior that proves the larger request is complete: all item-level capabilities are available together and are covered by tests and external validation when configured.",
            "",
            "## Tasks",
            "",
        ])
        for index, unit in enumerate(units, start=1):
            task_id = f"TASK-{index:03d}"
            ac_id = f"AC-{index:03d}"
            title = f"Implement {unit}" if unit != "production change" else "Implement production change"
            dep = "None" if index == 1 else f"TASK-{index - 1:03d}"
            lines.extend([
                f"### {task_id}: {title}",
                f"- Goal: Implement the independently verifiable deliverable `{unit}` using the detected project architecture.",
                "- Files: production/project files under Project path only.",
                "- Acceptance Criteria:",
                f"  - {ac_id}: `{unit}` is implemented and can be verified independently before final assembly.",
                "- Depends On:",
                f"  - {dep}",
                "- Assembly:",
                "  - This task contributes one item-level capability to the final requested behavior.",
                "- Validation:",
                "  - Covered by generated tests for this item and external validation when configured or present.",
                "",
            ])
        if multiple:
            ac_id = f"AC-{len(units) + 1:03d}"
            lines.extend([
                f"### {assembly_id}: Assemble and expose the complete requested behavior",
                "- Goal: Integrate the item-level deliverables into one coherent project result.",
                "- Files: production/project files under Project path only.",
                "- Acceptance Criteria:",
                f"  - {ac_id}: The project exposes the full requested behavior with all item-level deliverables working together.",
                "- Depends On:",
                f"  - {previous}",
                "- Assembly:",
                "  - Confirms the independent item tasks are connected through the final interface, module, command, or artifact requested by the user.",
                "- Validation:",
                "  - Covered by generated integration tests and external validation when configured or present.",
                "",
            ])
        lines.extend([
            "## Execution SOP",
            "- Step 1: Build production code only, one small task at a time.",
            "- Step 2: Generate tests only under the project test folder, using the task manifest as coverage input.",
            "- Step 3: Run automated tests.",
            "- Step 4: Run external validation when configured or present.",
            "- Step 5: Retry the failed owner step using concrete recovery analysis and error classification.",
            "",
            "## Acceptance & Stop Conditions",
            "- Build must create or modify at least one production/project artifact under Project path.",
            "- Small tasks must be implemented in order and assembled into one coherent project state.",
            "- Generated tests must cover item-level acceptance criteria and the assembled behavior.",
            "- Automated tests must pass.",
            "- External validation must pass when configured or present; otherwise it must record a skipped PASS.",
            "- Final Review, verifier-report.json, Diff Review, and Final Gate must complete.",
            "- Stop retrying when the configured max retry count is reached.",
            "",
            "## External Validation",
            "- If a validation script path is provided, that exact script is mandatory.",
            "- Otherwise use only the fallback validation script names configured by this workflow.",
            "- If no validation script is configured or found, external validation is skipped with a PASS result.",
            "",
            "## Assumptions",
            "- Use detected project language and structure.",
            "- Use reasonable defaults for unspecified minor details.",
            "",
            "## Suggested Todo Files",
        ])
        for index in range(1, len(units) + (2 if multiple else 1)):
            lines.append(f"- output/todos/TASK-{index:03d}.md")
        lines.append("")
        return "\n".join(lines)

    def _render_task_manifest(self, todo: str) -> str:
        task_ids = self._ordered_task_ids(todo)
        build_task_ids = [task_id for task_id in task_ids if self._task_owner(todo, task_id) == "build"]
        lines = [
            "# Task Manifest",
            "",
            "Status: READY" if task_ids else "Status: EMPTY",
            "",
            "## Purpose",
            "- Deterministic summary generated from `todo.md` so Build, Generate Tests, Retry, and Final Review share the same small-task order.",
            "- This does not let AI self-approve completion; Python gates still decide pass/fail from artifacts, tests, and external validation.",
            "- Build and Generate Tests may run as a per-task loop using this manifest; final completion still depends on verifier evidence.",
            "",
            "## Small Task Order",
        ]
        if task_ids:
            for index, task_id in enumerate(task_ids, start=1):
                owner = self._task_owner(todo, task_id)
                lines.append(f"{index}. {task_id} [owner={owner}]: {self._task_title(todo, task_id)}")
        else:
            lines.append("- No TASK-xxx items found.")
        lines.extend([
            "",
            "## Build Task Order",
        ])
        if build_task_ids:
            for index, task_id in enumerate(build_task_ids, start=1):
                lines.append(f"{index}. {task_id}: {self._task_title(todo, task_id)}")
        else:
            lines.append("- No build-owned TASK items found; Build will use the full requirement as one task.")
        lines.extend([
            "",
            "## Assembly Strategy",
            "- Implement small build-owned tasks in the listed order.",
            "- After each build-owned task, materialize only that task's production FILE blocks under Project Path.",
            "- After all small tasks are implemented, aggregate task outputs into `output/build-result.md` and run generated tests against the assembled project state.",
            "- Generate Tests should create focused tests for task-level acceptance criteria and the assembled behavior.",
            "- Run Test and External Validation are the source of truth for completion.",
            "",
            "## Retry Strategy",
            "- On failure, retry the owner step with concrete failure feedback.",
            "- Repeated errors are allowed to continue until max retries because small/local models may recover on later attempts.",
            "- When the same error repeats multiple times, the retry prompt should switch strategy instead of repeating the same output.",
            "- Workspace/path violations remain hard failures because they protect isolation.",
            "",
        ])
        return "\n".join(lines)

    @staticmethod
    def _safe_task_id(task_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "-", task_id or "TASK-001")

    def _render_task_todo_file(self, todo: str, task: dict[str, Any], *, index: int, total: int) -> str:
        task_id = str(task.get("id") or f"TASK-{index:03d}")
        task_title = str(task.get("title") or self._task_title(todo, task_id) or task_id)
        owner = str(task.get("owner") or self._task_owner(todo, task_id) or "build")
        section = self._task_section(todo, task_id).strip()
        if not section:
            section = f"### {task_id}: {task_title}\n- Goal: Complete this small task.\n- Acceptance Criteria:\n  - AC-001: The task output satisfies the user requirement.\n"
        lines = [
            f"# {task_id}: {task_title}",
            "",
            "Status: READY",
            "",
            "## Execution Scope",
            f"- Task ID: {task_id}",
            f"- Task index: {index}/{total}",
            f"- Owner step: {owner}",
            "- This file is the only task TODO that the current build/test loop should treat as active.",
            "- Do not implement unrelated TASK items unless they are already completed dependencies required by this task.",
            "",
            "## Source Task Section",
            "",
            section,
            "",
            "## Hard Rules",
            "- Follow the user requirement, project index, architecture, and this task TODO.",
            "- Keep writes inside the selected Project path only.",
            "- Build step must output production/project artifacts only, not tests.",
            "- Generate Tests step must output tests only, not production files.",
            "- Existing validation scripts are read-only acceptance tools unless the user explicitly asks to modify them.",
            "- Git commit and git push are forbidden; the user reviews git diff manually.",
            "",
            "## Completion Evidence",
            "- The task is complete only when task output materializes file changes and later tests/validation pass.",
            "- AI review can warn about risks, but Python verifier/test/validation decide final status.",
            "",
        ]
        return "\n".join(lines)

    def _write_task_todo_files(self, output_dir: Path, todo: str, manifest: str) -> list[str]:
        tasks = self._task_entries_from_manifest(manifest)
        if not tasks and re.search(r"\bTASK-\d{3}\b", todo or ""):
            tasks = [{"id": task_id, "owner": self._task_owner(todo, task_id), "title": self._task_title(todo, task_id)} for task_id in self._ordered_task_ids(todo)]
        todo_dir = output_dir / "todos"
        todo_dir.mkdir(parents=True, exist_ok=True)
        expected_names: set[str] = set()
        written: list[str] = []
        total = len(tasks)
        for index, task in enumerate(tasks, start=1):
            task_id = str(task.get("id") or f"TASK-{index:03d}")
            filename = f"{self._safe_task_id(task_id)}.md"
            expected_names.add(filename)
            content = self._render_task_todo_file(todo, task, index=index, total=total)
            write_text(todo_dir / filename, content)
            written.append(f"output/todos/{filename}")
        for path in todo_dir.glob("TASK-*.md"):
            if path.name not in expected_names:
                path.unlink()
        index_lines = [
            "# Task Todo Index",
            "",
            "Status: READY" if written else "Status: EMPTY",
            "",
            "Each file below is the scoped TODO for one task. Build and Generate Tests should treat only the current task file as active context.",
            "",
        ]
        if written:
            index_lines.extend(f"- {item}" for item in written)
        else:
            index_lines.append("- No task TODO files were generated.")
        write_text(output_dir / "todos" / "INDEX.md", "\n".join(index_lines) + "\n")
        return written

    @staticmethod
    def _task_entries_from_manifest(manifest: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(r"^\s*\d+\.\s+(TASK-\d{3})(?:\s+\[owner=([^\]]+)\])?:\s*(.+?)\s*$", re.MULTILINE)
        for match in pattern.finditer(manifest or ""):
            task_owner = (match.group(2) or "build").strip()
            if owner and task_owner != owner:
                continue
            key = (match.group(1), task_owner)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"id": match.group(1), "owner": task_owner, "title": match.group(3).strip()})
        return entries

    def _task_run(self, run: dict[str, Any], task: dict[str, Any], *, index: int, total: int, phase: str) -> dict[str, Any]:
        scoped = dict(run)
        # Per-task prompts must not inherit a long conversational memory from
        # earlier attempts/tasks.  The runner still receives deterministic task
        # context through prompt variables, but Qwen/OpenCode should solve only
        # the current small task.
        scoped["_force_fresh_qwen_session"] = True
        task_id = str(task.get("id") or "TASK-001")
        scoped["_current_task"] = {
            "id": task_id,
            "title": task.get("title", "Full requested change"),
            "owner": task.get("owner", "build"),
            "index": index,
            "total": total,
            "phase": phase,
            "todo_path": f"output/todos/{self._safe_task_id(task_id)}.md",
        }
        return scoped

    @staticmethod
    def _task_output_artifact(task_id: str, filename: str) -> str:
        return f"tasks/{WorkflowActions._safe_task_id(task_id)}/{filename}"

    @staticmethod
    def _render_aggregated_task_outputs(title: str, task_artifacts: list[tuple[str, str, str]]) -> str:
        lines = [f"# {title}", "", "Status: READY", "", "## Per-Task Outputs"]
        for task_id, task_title, content in task_artifacts:
            lines.extend(["", f"### {task_id}: {task_title}", "", content.strip(), ""])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_direct_edit_summary(title: str, task_id: str, task_title: str, files: list[tuple[str, str]]) -> str:
        lines = [
            f"# {title}",
            "",
            "Status: READY",
            "",
            f"## Task",
            f"- ID: {task_id}",
            f"- Title: {task_title}",
            "",
            "## Direct Agent Edits",
        ]
        for rel_path, content in files:
            markers = WorkflowActions._content_markers(content)
            marker_text = ", ".join(markers[:8]) if markers else "none detected"
            normalized_rel_path = str(rel_path).replace(chr(92), "/")
            lines.extend([
                f"- `{normalized_rel_path}`",
                f"  - Size: {len(content)} chars",
                f"  - Markers: {marker_text}",
            ])
        lines.extend(["", "The agent modified the project files directly. The platform recorded this summary from the before/after project snapshot and did not materialize FILE blocks."])
        return "\n".join(lines).rstrip() + "\n"

    async def implementation_review_step(self, run: dict[str, Any], artifact: str = "implementation-review.md") -> None:
        output_dir = Path(run["workspace"]) / "output"
        todo = read_text(output_dir / "todo.md")
        artifact = normalize_artifact_name(artifact)
        findings: list[str] = []
        required_markers = [
            "Status: READY",
            "## Requirement",
            "## Task Index",
            "## Tasks",
            "## Execution SOP",
            "## Acceptance & Stop Conditions",
            "## External Validation",
        ]
        missing = [marker for marker in required_markers if marker not in todo]
        if missing:
            findings.append("Missing required Todo marker(s): " + ", ".join(missing))
        if not re.search(r"\bTASK-\d{3}\b", todo):
            findings.append("Todo must include at least one TASK-xxx item.")
        if not re.search(r"\bAC-\d{3}\b", todo):
            findings.append("Todo must include task-level acceptance criteria AC-xxx.")
        if "external validation" not in todo.lower():
            findings.append("Todo must include the external validation step, which may skip when no script is configured or found.")
        if "stop condition" not in todo.lower() and "stop conditions" not in todo.lower():
            findings.append("Todo must include explicit acceptance and stop conditions for completion/retry control.")
        protected_validation_targets = self._todo_owned_validation_targets(run, todo)
        if protected_validation_targets:
            findings.append(
                "Todo must not list existing validation scripts as Build-owned task files: "
                + ", ".join(protected_validation_targets)
                + ". Validation scripts are external acceptance tools."
            )

        requirement = read_text(Path(run["workspace"]) / "requirement.md").strip() or "Complete the requested change."
        split_findings, deliverable_units = self._under_split_findings(requirement, todo)
        findings.extend(split_findings)

        remediated = False
        if findings:
            remediated = True
            fallback_todo = self._render_fallback_todo(requirement, deliverable_units)
            write_text(output_dir / "todo.md", fallback_todo)
            todo = fallback_todo
            await self.log(run, "implementation_review: repaired invalid or under-split todo.md with deterministic fallback")

        task_manifest = self._render_task_manifest(todo)
        write_text(output_dir / "task-manifest.md", task_manifest)
        task_todo_files = self._write_task_todo_files(output_dir, todo, task_manifest)
        project_dir = Path(run.get("project_path") or ROOT)
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        instructions = orchestrator.extract_user_instructions(requirement, project_dir)
        task_manifest_json = orchestrator.task_manifest_from_todo(todo, project_dir=project_dir, instructions=instructions)
        task_manifest_findings = orchestrator.validate_task_manifest(task_manifest_json, project_dir)
        workflow_instance = orchestrator.compile_workflow_instance(task_manifest_json, run_profile=str(run.get("run_profile") or "normal"))
        workflow_findings = orchestrator.validate_workflow_instance(workflow_instance, task_manifest_json)
        write_text(output_dir / "task-manifest.json", json.dumps(task_manifest_json, indent=2, ensure_ascii=False))
        write_text(output_dir / "generated-workflow-instance.json", json.dumps(workflow_instance, indent=2, ensure_ascii=False))
        write_text(output_dir / "workflow-instance-validation.md", orchestrator.render_validation_markdown(task_manifest_findings, workflow_findings))
        write_text(output_dir / "workflow-run-trace.md", orchestrator.render_run_trace(workflow_instance))
        if task_manifest_findings or workflow_findings:
            findings.extend(task_manifest_findings)
            findings.extend(workflow_findings)

        text = "\n".join(
            [
                "# Implementation Review",
                "",
                "Status: PASS",
                "Confidence: 1.00",
                "",
                "## Checks",
                "- Todo is concrete enough for automated Build.",
                "- Tasks include acceptance criteria.",
                "- Task granularity was checked against independent deliverables in the requirement.",
                "- task-manifest.md was generated from todo.md to stabilize small-task order and assembly.",
                "- task-manifest.json and generated-workflow-instance.json were compiled by Python from todo.md.",
                "- workflow-instance-validation.md and workflow-run-trace.md were generated as deterministic evidence.",
                "- output/todos/TASK-xxx.md files were generated so Build/Generate Tests can consume one small TODO at a time.",
                "- Acceptance and stop conditions are present.",
                "- Mandatory test and external validation stages are present.",
                "- Edits are constrained to the selected Project path.",
                "",
                "## Findings",
                *( ["- Invalid, unsafe, or under-split AI Todo was repaired deterministically: " + "; ".join(findings)] if remediated else ["- Deterministic review passed, including task granularity and validation ownership checks."] ),
                "",
            ]
        )
        write_text(output_dir / artifact, text)
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

    async def _run_multi_agent_review(
        self,
        run: dict[str, Any],
        step_record: dict[str, Any],
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool,
        agent_name: str | None,
    ) -> None:
        config = step_config(step_record)
        reviewers = config.get("reviewers") or []
        if not isinstance(reviewers, list) or not reviewers:
            await self.log(run, f"{step_record.get('key')}: multi_agent has no reviewers; falling back to current_session review")
            output = await self.run_agent_step(
                run,
                step_record["key"],
                prompt_name,
                artifact,
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            )
            decision = self._review_decision(output, config)
            if not decision["passed"]:
                raise WorkflowError(f"{step_record.get('key')}: review failed: {decision['reason']}")
            return

        output_dir = Path(run["workspace"]) / "output"
        stem = Path(artifact).stem
        suffix = Path(artifact).suffix or ".md"
        available_agents = self.agent_runner.agent_manager.available_agent_names()
        default_agent = agent_name or step_agent_name(step_record) or self.agent_runner.agent_manager.default_agent_name()
        decisions: list[dict[str, Any]] = []

        for index, reviewer in enumerate(reviewers, start=1):
            reviewer = reviewer if isinstance(reviewer, dict) else {}
            configured_agent = str(reviewer.get("provider") or reviewer.get("agent") or "").strip()
            provider = configured_agent if configured_agent in available_agents else default_agent
            profile = configured_agent if configured_agent and configured_agent not in available_agents else ""
            reviewer_prompt = str(reviewer.get("prompt") or prompt_name)
            reviewer_artifact = f"{stem}.reviewer-{index}{suffix}"
            weight = float(reviewer.get("weight") or 1)
            try:
                if profile:
                    await self.log(run, f"{step_record.get('key')}: reviewer {index} profile={profile} uses provider={provider}")
                output = await self.run_agent_step(
                    run,
                    step_record["key"],
                    reviewer_prompt,
                    reviewer_artifact,
                    allow_interaction=allow_interaction,
                    agent_name=provider,
                    fresh_session=True,
                )
                decision = self._review_decision(output, config)
                decision.update({"index": index, "agent": provider, "profile": profile, "weight": weight, "artifact": reviewer_artifact, "output": output})
            except Exception as exc:
                decision = {
                    "index": index,
                    "agent": provider,
                    "profile": profile,
                    "weight": weight,
                    "artifact": reviewer_artifact,
                    "output": "",
                    "passed": False,
                    "confidence": 0.0,
                    "reason": str(exc),
                }
                write_text(output_dir / reviewer_artifact, f"Status: FAIL\n\nReviewer execution failed:\n\n{exc}\n")
                await self.refresh_artifacts(run["id"])
            decisions.append(decision)

        aggregate = self._aggregate_review(config, decisions)
        write_text(output_dir / artifact, self._render_multi_agent_review(aggregate, decisions))
        await self.refresh_artifacts(run["id"])
        if not aggregate["passed"]:
            raise WorkflowError(f"{step_record.get('key')}: multi_agent review failed: {aggregate['reason']}")

    def _review_decision(self, output: str, config: dict[str, Any]) -> dict[str, Any]:
        text = output or ""
        lowered = text.lower()
        pass_keywords = self._split_keywords(config.get("passKeywords") or "PASS, APPROVED")
        fail_keywords = self._split_keywords(config.get("failKeywords") or "FAIL, BLOCKED")
        confidence = self._extract_confidence(text)

        fail_hit = next((keyword for keyword in fail_keywords if keyword.lower() in lowered), "")
        pass_hit = next((keyword for keyword in pass_keywords if keyword.lower() in lowered), "")
        if fail_hit:
            return {"passed": False, "confidence": confidence or 0.0, "reason": f"matched fail keyword: {fail_hit}"}
        if pass_keywords and not pass_hit:
            return {"passed": False, "confidence": confidence or 0.0, "reason": "no pass keyword matched"}
        effective_confidence = confidence if confidence is not None else (1.0 if pass_hit else 0.75)
        threshold = float(config.get("confidenceThreshold") or 0)
        if effective_confidence < threshold:
            return {"passed": False, "confidence": effective_confidence, "reason": f"confidence {effective_confidence:.2f} < threshold {threshold:.2f}"}
        return {"passed": True, "confidence": effective_confidence, "reason": pass_hit or "passed"}

    def _aggregate_review(self, config: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        aggregator = str(config.get("aggregatorFunction") or "keyword_confidence")
        if not decisions:
            return {"passed": True, "reason": "no reviewers configured", "aggregator": aggregator}
        pass_weight = sum(float(item.get("weight") or 1) for item in decisions if item.get("passed"))
        total_weight = sum(float(item.get("weight") or 1) for item in decisions) or 1
        if aggregator == "all_must_pass":
            passed = all(item.get("passed") for item in decisions)
            reason = "all reviewers passed" if passed else "at least one reviewer failed"
        elif aggregator == "majority_vote":
            passed = pass_weight > (total_weight / 2)
            reason = f"pass weight {pass_weight:g}/{total_weight:g}"
        else:
            threshold = float(config.get("confidenceThreshold") or 0)
            avg_confidence = sum(float(item.get("confidence") or 0) * float(item.get("weight") or 1) for item in decisions) / total_weight
            passed = pass_weight > 0 and avg_confidence >= threshold and not any(not item.get("passed") for item in decisions)
            reason = f"avg confidence {avg_confidence:.2f}, pass weight {pass_weight:g}/{total_weight:g}"
        return {"passed": passed, "reason": reason, "aggregator": aggregator, "pass_weight": pass_weight, "total_weight": total_weight}

    def _render_multi_agent_review(self, aggregate: dict[str, Any], decisions: list[dict[str, Any]]) -> str:
        status = "PASS" if aggregate.get("passed") else "FAIL"
        lines = [
            f"Status: {status}",
            "",
            "## Multi-Agent Review Summary",
            f"- Aggregator: {aggregate.get('aggregator')}",
            f"- Decision: {aggregate.get('reason')}",
            "",
            "## Reviewer Results",
        ]
        for item in decisions:
            reviewer_status = "PASS" if item.get("passed") else "FAIL"
            profile = f" / profile={item.get('profile')}" if item.get("profile") else ""
            lines.extend(
                [
                    f"### Reviewer {item.get('index')} - {reviewer_status}",
                    f"- Agent: {item.get('agent')}{profile}",
                    f"- Weight: {item.get('weight')}",
                    f"- Confidence: {float(item.get('confidence') or 0):.2f}",
                    f"- Reason: {item.get('reason')}",
                    f"- Artifact: {item.get('artifact')}",
                    "",
                    "```text",
                    str(item.get("output") or "").strip()[:4000],
                    "```",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _split_keywords(self, value: str) -> list[str]:
        return [part.strip() for part in re.split(r"[,\n]", str(value or "")) if part.strip()]

    def _extract_confidence(self, text: str) -> float | None:
        match = re.search(r"\bconfidence\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?|\d{1,3}(?:\.\d+)?)\s*%?", text, re.I)
        if not match:
            return None
        value = float(match.group(1))
        if value > 1:
            value = value / 100
        return max(0.0, min(1.0, value))

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

        # Prepare Project is deterministic for every workflow.  It writes only
        # architecture context and guard metadata; Qwen/OpenCode are reserved for
        # real Build / Auto Generation / Generate Tests direct edits.  This keeps
        # Step 1 fast and removes the old file-block materialization path.
        rendered = self.render_project_architecture_markdown(run, project_dir)
        before = read_text(architecture_path)
        write_text(output_dir / artifact, rendered)
        write_text(architecture_path, rendered)
        await self.refresh_artifacts(run["id"])
        if rendered != before:
            await self.log(run, "prepare_project: rendered deterministic architecture context")
        else:
            await self.log(run, "prepare_project: deterministic architecture context already up to date")

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
        try:
            await self.run_agent_step(run, "generate_tests", prompt_name, artifact, agent_name=agent_name, fresh_session=True)
        except UserInputRequired:
            raise

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
                "Use Qwen/OpenCode file edit/write tools to create project-specific tests, or output complete "
                "FILE/CONTENT/END_FILE blocks for test files under tests/."
            )

        validate_generated_test_files(direct_files)
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

    def _build_step_feedback(self, run: dict[str, Any]) -> str:
        input_dir = Path(run["workspace"]) / "input"
        return failure_feedback_for_step(read_text(input_dir / "failure-feedback.md"), "build")

    @staticmethod
    def _feedback_mentions_task(feedback: str, task_id: str) -> bool:
        if not feedback.strip() or not task_id.strip():
            return False
        return task_id in feedback or bool(re.search(rf"\btask\s+{re.escape(task_id)}\b", feedback, flags=re.I))

    @staticmethod
    def _retry_feedback_blocks(feedback: str) -> list[str]:
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

    @classmethod
    def _latest_retry_feedback_block(cls, feedback: str) -> str:
        blocks = cls._retry_feedback_blocks(feedback)
        return blocks[-1] if blocks else ""

    @classmethod
    def _latest_feedback_task_id(cls, feedback: str) -> str:
        block = cls._latest_retry_feedback_block(feedback)
        if not block:
            return ""
        match = re.search(r"\bTASK-\d{3}\b", block)
        return match.group(0) if match else ""

    @classmethod
    def _latest_feedback_mentions_task(cls, feedback: str, task_id: str) -> bool:
        block = cls._latest_retry_feedback_block(feedback)
        return cls._feedback_mentions_task(block, task_id)

    @staticmethod
    def _feedback_is_generic_for_task_loop(feedback: str) -> bool:
        block = WorkflowActions._latest_retry_feedback_block(feedback)
        return bool(block.strip()) and not bool(re.search(r"\bTASK-\d{3}\b", block))

    @staticmethod
    def _content_markers(content: str) -> list[str]:
        markers: list[str] = []
        patterns = [
            r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
            r"^\s*class\s+([A-Za-z_]\w*)\b",
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
            r"^\s*#{1,6}\s+(.+?)\s*$",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content or "", flags=re.MULTILINE):
                marker = str(match.group(1)).strip()
                if marker and marker not in markers:
                    markers.append(marker)
        return markers[:40]

    @staticmethod
    def _task_state_path(output_dir: Path, task_id: str, phase: str) -> Path:
        safe_task_id = "".join(ch if ch.isalnum() or ch in {"_", ".", "-"} else "-" for ch in str(task_id or "TASK-000"))
        return output_dir / "tasks" / safe_task_id / f"{phase}-state.json"

    def _write_task_direct_state(self, output_dir: Path, project_dir: Path, task_id: str, phase: str, files: list[tuple[str, str]]) -> None:
        state_files: list[dict[str, Any]] = []
        for rel_path, content in files:
            markers = self._content_markers(content)
            state_files.append({"path": rel_path.replace("\\", "/"), "markers": markers})
        path = self._task_state_path(output_dir, task_id, phase)
        write_text(path, json.dumps({"task_id": task_id, "phase": phase, "files": state_files}, indent=2, ensure_ascii=False))

    def _task_direct_state_is_satisfied(self, output_dir: Path, project_dir: Path, task_id: str, phase: str) -> bool:
        path = self._task_state_path(output_dir, task_id, phase)
        if not path.is_file():
            return False
        try:
            state = json.loads(read_text(path))
        except json.JSONDecodeError:
            return False
        files = state.get("files") if isinstance(state, dict) else []
        if not isinstance(files, list) or not files:
            return False
        for item in files:
            if not isinstance(item, dict):
                return False
            rel_path = str(item.get("path") or "").strip().replace("\\", "/")
            markers = [str(marker) for marker in item.get("markers") or [] if str(marker).strip()]
            if not rel_path:
                return False
            target = project_dir / rel_path
            if not target.is_file():
                return False
            try:
                actual = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                return False
            if any(marker not in actual for marker in markers):
                return False
        return True

    def _validate_previous_direct_task_states_preserved(
        self,
        output_dir: Path,
        project_dir: Path,
        *,
        current_index: int,
        current_task_id: str,
        phase: str,
    ) -> None:
        missing: list[str] = []
        for task_dir in sorted(path for path in (output_dir / "tasks").glob("TASK-*") if path.is_dir()):
            match = re.fullmatch(r"TASK-(\d{3})", task_dir.name)
            if not match:
                continue
            task_number = int(match.group(1))
            if not current_index or task_number >= current_index:
                continue
            state_path = task_dir / f"{phase}-state.json"
            if not state_path.is_file():
                continue
            try:
                state = json.loads(read_text(state_path))
            except json.JSONDecodeError:
                continue
            for item in state.get("files") or []:
                if not isinstance(item, dict):
                    continue
                rel_path = str(item.get("path") or "").strip().replace("\\", "/")
                markers = [str(marker) for marker in item.get("markers") or [] if str(marker).strip()]
                if not rel_path or not markers:
                    continue
                target = project_dir / rel_path
                if not target.is_file():
                    missing.append(f"{current_task_id} removed previous task file {rel_path} from {task_dir.name}")
                    continue
                try:
                    actual = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                lost = [marker for marker in markers if marker not in actual]
                if lost:
                    missing.append(
                        f"{current_task_id} changed {rel_path} and lost previous marker(s) from {task_dir.name}: {', '.join(lost[:8])}"
                    )
        if missing:
            raise WorkflowError(
                "A direct agent edit removed previously completed task behavior. "
                "Retry the current task and preserve earlier task results. " + "; ".join(missing)
            )

    def _task_artifact_is_satisfied(self, project_dir: Path, artifact_path: Path) -> bool:
        files = extract_build_files(read_text(artifact_path))
        if not files:
            return False
        for rel_path, expected in files:
            target = project_dir / rel_path.strip().strip("`").replace("\\", "/")
            if not target.is_file():
                return False
            try:
                actual = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                return False
            markers = self._content_markers(expected)
            if markers:
                if any(marker not in actual for marker in markers):
                    return False
            elif actual != expected:
                return False
        return True

    def _previous_task_artifacts(self, output_dir: Path, current_index: int, filename: str) -> list[tuple[str, Path]]:
        artifacts: list[tuple[str, Path]] = []
        task_root = output_dir / "tasks"
        if not task_root.exists():
            return artifacts
        for task_dir in sorted(path for path in task_root.iterdir() if path.is_dir()):
            match = re.fullmatch(r"TASK-(\d{3})", task_dir.name)
            if not match:
                continue
            if int(match.group(1)) >= current_index:
                continue
            artifact_path = task_dir / filename
            if artifact_path.is_file():
                artifacts.append((task_dir.name, artifact_path))
        return artifacts

    def _validate_previous_task_markers_preserved(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_task_id: str,
        current_index: int,
        current_files: list[tuple[str, str]],
        filename: str,
    ) -> None:
        changed_paths = {rel_path.strip().strip("`").replace("\\", "/") for rel_path, _ in current_files}
        if not changed_paths:
            return
        missing: list[str] = []
        for previous_task_id, artifact_path in self._previous_task_artifacts(output_dir, current_index, filename):
            for rel_path, previous_content in extract_build_files(read_text(artifact_path)):
                normalized = rel_path.strip().strip("`").replace("\\", "/")
                if normalized not in changed_paths:
                    continue
                markers = self._content_markers(previous_content)
                if not markers:
                    continue
                target = project_dir / normalized
                try:
                    actual = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    actual = ""
                lost = [marker for marker in markers if marker not in actual]
                if lost:
                    missing.append(
                        f"{current_task_id} overwrote previous task output from {previous_task_id} in {normalized}; "
                        f"missing preserved marker(s): {', '.join(lost[:8])}"
                    )
        if missing:
            raise WorkflowError(
                "Task output appears to have overwritten already completed task behavior. "
                "When editing a shared file, output the complete file and preserve previous task results. "
                + "; ".join(missing)
            )

    @staticmethod
    def _loose_code_from_agent_output(output: str) -> str:
        text = (output or "").strip()
        if not text or "FILE:" in text:
            return ""
        fences = list(re.finditer(r"```(?P<lang>[A-Za-z0-9_.+-]*)\s*\r?\n(?P<body>.*?)\r?\n```", text, flags=re.DOTALL))
        if fences:
            # Prefer an explicit source-code fence.  Ignore prose-only markdown fences.
            for match in reversed(fences):
                lang = (match.group("lang") or "").lower()
                body = match.group("body").strip()
                if lang in {"python", "py", "javascript", "js", "typescript", "ts", "java", "csharp", "cs", "go", "rust", "rs"}:
                    return body.rstrip() + "\n"
            if len(fences) == 1:
                body = fences[0].group("body").strip()
                if re.search(r"(?m)^\s*(?:def|class|import|from)\s+", body):
                    return body.rstrip() + "\n"
            return ""
        if re.search(r"(?m)^\s*(?:def|class|import|from)\s+", text):
            return text.rstrip() + "\n"
        return ""

    @staticmethod
    def _is_python_like_code(content: str) -> bool:
        return bool(re.search(r"(?m)^\s*(?:def|class|import|from)\s+", content or ""))

    @staticmethod
    def _sanitized_module_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "main").strip().lower()).strip("_")
        return cleaned or "main"

    def _preferred_loose_output_path(self, project_dir: Path, output_dir: Path, current_index: int, filename: str, content: str) -> str:
        # A model that omits FILE blocks usually emitted a fragment for the same
        # shared file used by earlier tasks.  Prefer the most recent earlier
        # production path so the task loop converges instead of restarting from
        # TASK-001.
        previous = self._previous_task_artifacts(output_dir, current_index, filename)
        for _task_id, artifact_path in reversed(previous):
            paths = [rel_path.strip().strip("`").replace("\\", "/") for rel_path, _ in extract_build_files(read_text(artifact_path))]
            for rel_path in reversed(paths):
                if rel_path and not rel_path.startswith("tests/"):
                    return rel_path
        snapshot = project_file_snapshot(project_dir)
        source_paths = [path.replace("\\", "/") for path in sorted(snapshot) if not path.replace("\\", "/").startswith("tests/") and Path(path).suffix.lower() in {".py", ".js", ".ts", ".java", ".cs", ".go", ".rs"}]
        if len(source_paths) == 1:
            return source_paths[0]
        if self._is_python_like_code(content):
            return f"src/{self._sanitized_module_name(project_dir.name)}.py"
        return "src/main.txt"

    def _coerce_loose_task_output_to_files(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_index: int,
        filename: str,
        output: str,
    ) -> list[tuple[str, str]]:
        code = self._loose_code_from_agent_output(output)
        if not code:
            return []
        rel_path = self._preferred_loose_output_path(project_dir, output_dir, current_index, filename, code)
        target = project_dir / rel_path
        content = code.rstrip() + "\n"
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                existing = ""
            existing_markers = self._content_markers(existing)
            new_markers = self._content_markers(content)
            if existing.strip() and existing_markers and new_markers:
                missing_existing = [marker for marker in existing_markers if marker not in content]
                novel_new = [marker for marker in new_markers if marker not in existing]
                if missing_existing and novel_new:
                    content = existing.rstrip() + "\n\n" + content.lstrip()
        return [(rel_path, content)]

    def _merge_candidate_with_existing_if_needed(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_index: int,
        files: list[tuple[str, str]],
        filename: str,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        adjusted: list[tuple[str, str]] = []
        notes: list[str] = []
        for rel_path, content in files:
            normalized = rel_path.strip().strip("`").replace("\\", "/")
            expected_markers: list[str] = []
            for _previous_task_id, artifact_path in self._previous_task_artifacts(output_dir, current_index, filename):
                for previous_rel, previous_content in extract_build_files(read_text(artifact_path)):
                    if previous_rel.strip().strip("`").replace("\\", "/") != normalized:
                        continue
                    for marker in self._content_markers(previous_content):
                        if marker not in expected_markers:
                            expected_markers.append(marker)
            missing = [marker for marker in expected_markers if marker not in content]
            target = project_dir / normalized
            if missing and target.is_file():
                try:
                    existing = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    existing = ""
                new_markers = [marker for marker in self._content_markers(content) if marker not in existing]
                if existing.strip() and new_markers:
                    merged = existing.rstrip() + "\n\n" + content.lstrip().rstrip() + "\n"
                    adjusted.append((rel_path, merged))
                    notes.append(f"{normalized} preserved previous marker(s): {', '.join(missing[:6])}")
                    continue
            adjusted.append((rel_path, content))
        return adjusted, notes

    async def build_step(self, run: dict[str, Any], prompt_name: str = "05_build.md", artifact: str = "build-result.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        await self._ensure_project_agent_configs(run, project_dir)
        before = project_file_snapshot(project_dir)

        if self._is_auto_development_workflow(run):
            manifest = read_text(output_dir / "task-manifest.md")
            tasks = self._task_entries_from_manifest(manifest, owner="build")
            if not tasks:
                tasks = [{"id": "TASK-001", "owner": "build", "title": "Full requested production change"}]
            total = len(tasks)
            build_feedback = self._build_step_feedback(run)
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
                ) or self._feedback_is_generic_for_task_loop(build_feedback)
                if (
                    task_artifact_path.is_file()
                    and not task_has_feedback
                    and (
                        self._task_direct_state_is_satisfied(output_dir, project_dir, task_id, "build")
                        or (self._file_blocks_allowed_as_direct_edits() and self._task_artifact_is_satisfied(project_dir, task_artifact_path))
                    )
                ):
                    task_result = read_text(task_artifact_path)
                    task_artifacts.append((task_id, task_title, task_result))
                    await self.log(run, f"build/{task_id}: skipped because direct edits from this task are already present and preserved")
                    continue

                scoped_run = self._task_run(run, task, index=index, total=total, phase="build")
                task_before = project_file_snapshot(project_dir)
                await self.log(run, f"build: task loop {index}/{total} {task_id} - {task_title}")
                try:
                    await self.run_agent_step(scoped_run, "build", prompt_name, task_artifact, agent_name=agent_name, fresh_session=True)
                except UserInputRequired:
                    raise

                direct_files = self._direct_edit_files_from_snapshot(
                    project_dir,
                    task_before,
                    project_file_snapshot(project_dir),
                    forbid_test_files=True,
                )
                if not direct_files:
                    direct_files = self._apply_file_blocks_for_direct_edit(
                        project_dir,
                        read_text(task_artifact_path),
                        forbid_test_files=True,
                        validation_script=run.get("validation_script"),
                        fallback_scripts=self._fallback_validation_scripts(run),
                        output_label=f"agent build task {task_id} file block direct edit",
                    )
                if not direct_files:
                    raise WorkflowError(
                        f"build task {task_id} did not directly create or modify production files under Project Path: {project_dir}. "
                        "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks for each production file."
                    )

                validate_build_files_are_not_tests(direct_files)
                validate_build_files_do_not_overwrite_validation_scripts(
                    project_dir,
                    direct_files,
                    validation_script=run.get("validation_script"),
                    fallback_scripts=self._fallback_validation_scripts(run),
                )
                self._write_task_direct_state(output_dir, project_dir, task_id, "build", direct_files)
                self._validate_previous_direct_task_states_preserved(
                    output_dir,
                    project_dir,
                    current_index=index,
                    current_task_id=task_id,
                    phase="build",
                )
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
                    f"build did not directly create or modify production files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks."
                )
            return

        try:
            await self.run_agent_step(run, "build", prompt_name, artifact, agent_name=agent_name, fresh_session=True)
        except UserInputRequired:
            raise

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
                forbid_test_files=True,
                validation_script=run.get("validation_script"),
                fallback_scripts=self._fallback_validation_scripts(run),
                output_label="agent build file block direct edit",
            )
        if not direct_files:
            raise WorkflowError(
                f"build did not directly create or modify production files under Project Path: {project_dir}. "
                "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks."
            )
        validate_build_files_are_not_tests(direct_files)
        validate_build_files_do_not_overwrite_validation_scripts(
            project_dir,
            direct_files,
            validation_script=run.get("validation_script"),
            fallback_scripts=self._fallback_validation_scripts(run),
        )
        summary = self._render_direct_edit_summary("Build Direct Edit Result", "BUILD", "Production changes", direct_files)
        write_text(output_dir / artifact, summary)
        self._write_task_direct_state(output_dir, project_dir, "BUILD", "build", direct_files)
        await self.log(run, "build: accepted direct agent production edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
        await self.refresh_artifacts(run["id"])

    async def generate_task_prompts_step(self, run: dict[str, Any], artifact: str = "task-manifest.md") -> None:
        """Generate Adaptive task manifest and per-task prompts as a visible step."""
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        generator = TaskPromptGenerator()
        manifest = generator.generate(run, output_dir=output_dir, project_dir=project_dir)
        await self.refresh_artifacts(run["id"])
        await self.log(run, f"generate_task_prompts: generated {len(manifest.get('tasks') or [])} adaptive task prompt(s)")

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

        if self._is_adaptive_workflow(run):
            manifest_path = output_dir / "task-manifest.json"
            tasks: list[dict[str, Any]] = []
            if manifest_path.is_file():
                try:
                    parsed = json.loads(read_text(manifest_path))
                    raw_tasks = parsed.get("tasks") if isinstance(parsed, dict) else []
                    if isinstance(raw_tasks, list):
                        tasks = [task for task in raw_tasks if isinstance(task, dict)]
                except json.JSONDecodeError:
                    tasks = []
            if not tasks:
                tasks = [{"id": "TASK-001", "title": "Complete requested adaptive task"}]

            task_artifacts: list[tuple[str, str, str]] = []
            total = len(tasks)
            generation_feedback = failure_feedback_for_step(read_text(Path(run["workspace"]) / "input" / "failure-feedback.md"), "auto_generation")
            for index, task in enumerate(tasks, start=1):
                task_id = str(task.get("id") or f"TASK-{index:03d}")
                task_title = str(task.get("title") or task_id)
                task_artifact = self._task_output_artifact(task_id, "adaptive-generation-result.md")
                task_artifact_path = output_dir / task_artifact
                task_artifact_path.parent.mkdir(parents=True, exist_ok=True)
                task_has_feedback = self._latest_feedback_mentions_task(
                    generation_feedback,
                    task_id,
                ) or self._feedback_is_generic_for_task_loop(generation_feedback)
                if (
                    task_artifact_path.is_file()
                    and not task_has_feedback
                    and (
                        self._task_direct_state_is_satisfied(output_dir, project_dir, task_id, "auto_generation")
                        or (self._file_blocks_allowed_as_direct_edits() and self._task_artifact_is_satisfied(project_dir, task_artifact_path))
                    )
                ):
                    task_result = read_text(task_artifact_path)
                    task_artifacts.append((task_id, task_title, task_result))
                    await self.log(run, f"auto_generation/{task_id}: skipped because direct edits from this task are already present and preserved")
                    continue

                scoped_run = self._task_run(run, task, index=index, total=total, phase="adaptive_generation")
                task_before = project_file_snapshot(project_dir)
                await self.log(run, f"auto_generation: adaptive task loop {index}/{total} {task_id} - {task_title}")
                try:
                    await self.run_agent_step(scoped_run, "auto_generation", prompt_name, task_artifact, agent_name=agent_name, fresh_session=True)
                except UserInputRequired:
                    raise

                direct_files = self._direct_edit_files_from_snapshot(
                    project_dir,
                    task_before,
                    project_file_snapshot(project_dir),
                )
                if not direct_files:
                    direct_files = self._apply_file_blocks_for_direct_edit(
                        project_dir,
                        read_text(task_artifact_path),
                        validation_script=run.get("validation_script"),
                        fallback_scripts=self._fallback_validation_scripts(run),
                        output_label=f"agent adaptive task {task_id} file block direct edit",
                    )
                if not direct_files:
                    raise WorkflowError(
                        f"auto_generation task {task_id} did not directly create or modify files under Project Path: {project_dir}. "
                        "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks."
                    )
                validate_build_files_do_not_overwrite_validation_scripts(
                    project_dir,
                    direct_files,
                    validation_script=run.get("validation_script"),
                    fallback_scripts=self._fallback_validation_scripts(run),
                )
                validate_test_code_is_separate(direct_files)
                self._write_task_direct_state(output_dir, project_dir, task_id, "auto_generation", direct_files)
                self._validate_previous_direct_task_states_preserved(
                    output_dir,
                    project_dir,
                    current_index=index,
                    current_task_id=task_id,
                    phase="auto_generation",
                )
                task_result = self._render_direct_edit_summary("Adaptive Generation Direct Edit Result", task_id, task_title, direct_files)
                write_text(task_artifact_path, task_result)
                task_artifacts.append((task_id, task_title, task_result))
                await self.log(run, f"auto_generation/{task_id}: accepted direct agent edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
                if await self._external_validation_passes_now(run, output_dir):
                    break

            write_text(output_dir / artifact, self._render_aggregated_task_outputs("Adaptive Generation Result", task_artifacts))
            await self.refresh_artifacts(run["id"])
            after = project_file_snapshot(project_dir)
            if not snapshot_changed(before, after) and not task_artifacts:
                raise WorkflowError(
                    f"auto_generation did not directly create or modify files under Project Path: {project_dir}. "
                    "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks."
                )
            return

        try:
            await self.run_agent_step(run, "auto_generation", prompt_name, artifact, agent_name=agent_name, fresh_session=True)
        except UserInputRequired:
            raise
        direct_files = self._direct_edit_files_from_snapshot(
            project_dir,
            before,
            project_file_snapshot(project_dir),
        )
        if not direct_files:
            direct_files = self._apply_file_blocks_for_direct_edit(
                project_dir,
                read_text(output_dir / artifact),
                validation_script=run.get("validation_script"),
                fallback_scripts=self._fallback_validation_scripts(run),
                output_label="agent adaptive file block direct edit",
            )
        if not direct_files:
            raise WorkflowError(
                f"auto_generation did not directly create or modify files under Project Path: {project_dir}. "
                "Use Qwen/OpenCode file edit/write tools, or output complete FILE/CONTENT/END_FILE blocks."
            )
        validate_build_files_do_not_overwrite_validation_scripts(
            project_dir,
            direct_files,
            validation_script=run.get("validation_script"),
            fallback_scripts=self._fallback_validation_scripts(run),
        )
        validate_test_code_is_separate(direct_files)
        summary = self._render_direct_edit_summary("Adaptive Generation Direct Edit Result", "AUTO-GENERATION", "Adaptive generation", direct_files)
        write_text(output_dir / artifact, summary)
        self._write_task_direct_state(output_dir, project_dir, "AUTO-GENERATION", "auto_generation", direct_files)
        await self.log(run, "auto_generation: accepted direct agent edit(s): " + ", ".join(rel_path for rel_path, _ in direct_files))
        await self.refresh_artifacts(run["id"])

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

    def action_for_step(self, run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
        key = step_record["key"]
        config = step_config(step_record)
        step_type = step_record.get("type") or config.get("type") or "ai"
        allow_interaction = bool(step_record.get("allow_interaction"))
        run_agent = str(run.get("agent") or "").strip()
        agent_name = run_agent or step_agent_name(step_record) or None

        registry: dict[str, Callable[[], Awaitable[None]]] = {
            "prepare_project": lambda: self.prepare_project_step(
                run,
                step_prompt_name(step_record, "00_prepare.md"),
                step_artifact_name(step_record, "architecture.md"),
                agent_name=agent_name,
            ),
            "generate_spec": lambda: self.generate_spec_step(
                run,
                step_prompt_name(step_record, "01_spec.md"),
                step_artifact_name(step_record, "spec.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            ),
            "validate_spec": lambda: self.validate_or_repair_spec(run, output_dir),
            "review_spec": lambda: self.review_step(
                run,
                key,
                step_prompt_name(step_record, "02_review_spec.md"),
                step_artifact_name(step_record, "spec-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            ),
            "spec_gate": lambda: asyncio.to_thread(self.functions.require_status, output_dir / step_artifact_name(step_record, "spec-review.md"), "PASS"),
            "generate_todo": lambda: self.generate_todo_step(
                run,
                step_prompt_name(step_record, "03_todo.md"),
                step_artifact_name(step_record, "todo.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            ),
            "validate_todo": lambda: self.validate_or_repair_todo(run, output_dir),
            "review_todo": lambda: self.review_step(
                run,
                key,
                step_prompt_name(step_record, "04_review_todo.md"),
                step_artifact_name(step_record, "todo-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            ),
            "implementation_review": lambda: (
                self.implementation_review_step(run, step_artifact_name(step_record, "implementation-review.md"))
                if self._is_auto_development_workflow(run)
                else self.review_step(
                    run,
                    key,
                    step_prompt_name(step_record, "02_implementation_review.md"),
                    step_artifact_name(step_record, "implementation-review.md"),
                    allow_interaction=allow_interaction,
                    agent_name=agent_name,
                )
            ),
            "todo_gate": lambda: asyncio.to_thread(self.functions.require_status, output_dir / step_artifact_name(step_record, "todo-review.md"), "PASS"),
            "generate_tests": lambda: self.generate_tests_step(
                run,
                step_prompt_name(step_record, "07_test.md"),
                step_artifact_name(step_record, "test-plan.md"),
                agent_name=agent_name,
            ),
            "build": lambda: self.build_step(
                run,
                step_prompt_name(step_record, "05_build.md"),
                step_artifact_name(step_record, "build-result.md"),
                agent_name=agent_name,
            ),
            "generate_task_prompts": lambda: self.generate_task_prompts_step(
                run,
                step_artifact_name(step_record, "task-manifest.md"),
            ),
            "auto_generation": lambda: self.adaptive_generation_step(
                run,
                step_prompt_name(step_record, "00_auto_generation.md"),
                step_artifact_name(step_record, "auto-generation-result.md"),
                agent_name=agent_name,
            ),
            "run_test": lambda: self.functions.call_python_functions(
                self._run_with_step_context(run, step_record),
                step_function_names(step_record) or ["run_pytest"],
                output_dir,
            ),
            "consensus_security_scan": lambda: self.consensus_security_scan_step(
                run,
                step_prompt_name(step_record, "00_security_candidate_scan.md"),
                agent_name=agent_name,
            ),
            "consensus_agent": lambda: self.consensus_agent_step(
                run,
                key,
                step_prompt_name(step_record, f"{key}.md"),
                agent_name=agent_name,
            ),
            "final_review": lambda: (
                self.final_review_step(run, step_artifact_name(step_record, "final-review.md"))
                if self._is_auto_development_workflow(run)
                else self.review_step(
                    run,
                    key,
                    step_prompt_name(step_record, "06_final_review.md"),
                    step_artifact_name(step_record, "final-review.md"),
                    allow_interaction=allow_interaction,
                    agent_name=agent_name,
                )
            ),
            "final_gate": lambda: asyncio.to_thread(self.functions.require_status, output_dir / step_artifact_name(step_record, "final-review.md"), "PASS"),
        }
        if key in registry:
            return registry[key]

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
