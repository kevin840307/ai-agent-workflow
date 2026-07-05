from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.auto_workflow import orchestrator
from app.core.paths import read_text, write_text
from app.runtime_modules.files import project_overview, project_profile, render_project_index_markdown
from app.workflow_runtime.thinking import normalize_thinking_level, render_thinking_guidance, thinking_label


class TaskPromptGenerator:
    """Generate a deterministic task manifest and per-task prompts for adaptive runs.

    The visible workflow still has a fixed shape.  This class only generates the
    dynamic task plan and the task-scoped prompts consumed by the internal loop.
    It deliberately does not create, edit, or persist .workflow definitions.
    """

    def generate(self, run: dict[str, Any], *, output_dir: Path, project_dir: Path) -> dict[str, Any]:
        requirement = read_text(Path(run["workspace"]) / "requirement.md").strip()
        manifest = self._manifest_from_existing_todo_or_requirement(output_dir, project_dir, requirement)
        if not isinstance(manifest.get("tasks"), list) or not manifest["tasks"]:
            manifest = self._fallback_manifest(requirement, project_dir)
        manifest = self._normalize_manifest(manifest, requirement, project_dir)
        findings = orchestrator.validate_task_manifest(manifest, project_dir)
        if findings:
            # Keep the run usable by falling back to one bounded task instead of
            # failing before the user gets any result.  The generated validation
            # artifact still records the deterministic downgrade.
            manifest = self._fallback_manifest(requirement, project_dir)
            findings = orchestrator.validate_task_manifest(manifest, project_dir)
        instance = orchestrator.compile_workflow_instance(manifest, run_profile=str(run.get("run_profile") or "normal"))
        workflow_findings = orchestrator.validate_workflow_instance(instance, manifest)
        thinking_level = normalize_thinking_level(run.get("thinking_level"), default="medium" if run.get("thinking_level_override") else "none")
        architecture_contract = self._build_architecture_contract(run, output_dir, project_dir, requirement)
        workflow_spec = self._build_workflow_spec(manifest, instance, thinking_level, architecture_contract)
        self._write_outputs(run, output_dir, project_dir, manifest, instance, findings, workflow_findings, workflow_spec, thinking_level, architecture_contract)
        return manifest

    def _manifest_from_existing_todo_or_requirement(self, output_dir: Path, project_dir: Path, requirement: str) -> dict[str, Any]:
        todo = read_text(output_dir / "todo.md")
        if "TASK-" in todo and "Status: READY" in todo:
            manifest = orchestrator.task_manifest_from_todo(todo, project_dir=project_dir)
            manifest["goal"] = manifest.get("goal") or requirement
            return manifest
        return self._manifest_from_requirement(requirement, project_dir)

    def _manifest_from_requirement(self, requirement: str, project_dir: Path) -> dict[str, Any]:
        units = self._extract_independent_units(requirement)
        if not units:
            return self._fallback_manifest(requirement, project_dir)

        tasks = self._tasks_from_units(units, project_dir)
        return {
            "status": "READY",
            "schema_version": 1,
            "goal": requirement or "Complete the requested adaptive task.",
            "deliverables": units,
            "task_strategy": "cohesive_deliverable_batches" if self._should_group_units(units) else "independent_deliverable_tasks",
            "tasks": tasks,
            "final_acceptance": {
                "automated_tests_required": True,
                "deliverable_coverage_required": True,
                "external_validation_required_when_configured": True,
                "verifier_report_required": False,
            },
        }

    def _tasks_from_units(self, units: list[str], project_dir: Path) -> list[dict[str, Any]]:
        if self._should_group_units(units):
            return self._cohesive_group_tasks(units, project_dir)

        tasks: list[dict[str, Any]] = []
        previous: str | None = None
        for index, unit in enumerate(units, start=1):
            task_id = f"TASK-{index:03d}"
            tasks.append(
                {
                    "id": task_id,
                    "title": f"Implement {unit}",
                    "owner": "build",
                    "depends_on": [previous] if previous else [],
                    "allowed_write_paths": self._allowed_write_paths(project_dir),
                    "deliverables": [unit],
                    "acceptance": [
                        f"`{unit}` is implemented as a reusable project artifact.",
                        f"Focused tests or validation evidence cover `{unit}`.",
                        f"A traceability label for `{unit}` is present in code, tests, or validation evidence.",
                    ],
                    "source": "adaptive_requirement",
                }
            )
            previous = task_id
        if len(tasks) > 1:
            assembly_id = f"TASK-{len(tasks) + 1:03d}"
            tasks.append(
                {
                    "id": assembly_id,
                    "title": "Assemble and verify the complete requested behavior",
                    "owner": "build",
                    "depends_on": [previous] if previous else [],
                    "allowed_write_paths": self._allowed_write_paths(project_dir),
                    "deliverables": units,
                    "acceptance": [
                        "All item-level deliverables are exposed through one coherent project interface or artifact set.",
                        "Final tests or external validation can verify the full user request.",
                        "Traceability evidence covers every requested deliverable.",
                    ],
                    "source": "adaptive_requirement",
                }
            )
        return tasks

    def _cohesive_group_tasks(self, units: list[str], project_dir: Path) -> list[dict[str, Any]]:
        # A cohesive list should not become one agent task per item, because later
        # tasks can overwrite earlier work.  It also should not become one
        # unbounded mega-task.  Batch implementation by bounded chunks, then run
        # one whole-set verification task.  This is structural and domain-neutral:
        # grouping is based on item similarity, not specific keywords.
        chunk_size = 5
        chunks = [units[index : index + chunk_size] for index in range(0, len(units), chunk_size)]
        tasks: list[dict[str, Any]] = []
        previous: str | None = None
        for index, chunk in enumerate(chunks, start=1):
            task_id = f"TASK-{index:03d}"
            title = "Implement deliverable batch" if len(chunks) > 1 else "Implement complete deliverable set"
            if len(chunks) > 1:
                title = f"{title} {index}/{len(chunks)}"
            tasks.append(
                {
                    "id": task_id,
                    "title": title,
                    "owner": "build",
                    "depends_on": [previous] if previous else [],
                    "allowed_write_paths": self._allowed_write_paths(project_dir),
                    "deliverables": chunk,
                    "deliverable_set": units,
                    "acceptance": [
                        "Implement this batch inside the same existing module/interface family as the rest of the deliverable set.",
                        "Preserve any deliverables from previous batches; never rewrite the module to only contain the current batch.",
                        *[f"`{item}` is implemented and traceable." for item in chunk],
                    ],
                    "source": "adaptive_requirement_grouped",
                }
            )
            previous = task_id

        verification_id = f"TASK-{len(tasks) + 1:03d}"
        tasks.append(
            {
                "id": verification_id,
                "title": "Verify complete deliverable set",
                "owner": "build",
                "depends_on": [previous] if previous else [],
                "allowed_write_paths": self._allowed_write_paths(project_dir),
                "deliverables": units,
                "deliverable_set": units,
                "acceptance": [
                    "Focused tests, validation evidence, or traceability coverage verify every requested deliverable.",
                    "The final project interface exposes all requested deliverables coherently.",
                    *[f"`{item}` has focused verification coverage." for item in units],
                ],
                "source": "adaptive_requirement_grouped_verification",
            }
        )
        return tasks

    def _fallback_manifest(self, requirement: str, project_dir: Path) -> dict[str, Any]:
        return {
            "status": "READY",
            "schema_version": 1,
            "goal": requirement or "Complete the requested adaptive task.",
            "tasks": [
                {
                    "id": "TASK-001",
                    "title": "Complete the requested adaptive task",
                    "owner": "build",
                    "depends_on": [],
                    "allowed_write_paths": self._allowed_write_paths(project_dir),
                    "acceptance": ["The requested project change is implemented and verified."],
                    "source": "adaptive_fallback",
                }
            ],
            "final_acceptance": {
                "automated_tests_required": True,
                "external_validation_required_when_configured": True,
                "verifier_report_required": False,
            },
        }

    def _normalize_manifest(self, manifest: dict[str, Any], requirement: str, project_dir: Path) -> dict[str, Any]:
        normalized = dict(manifest)
        normalized["status"] = "READY"
        normalized["schema_version"] = normalized.get("schema_version") or 1
        normalized["goal"] = normalized.get("goal") or requirement or "Complete the requested adaptive task."
        tasks = []
        previous_ids: set[str] = set()
        for index, task in enumerate(normalized.get("tasks") or [], start=1):
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or f"TASK-{index:03d}")
            if not re.fullmatch(r"TASK-\d{3}", task_id):
                task_id = f"TASK-{index:03d}"
            owner = str(task.get("owner") or "build")
            if owner not in {"build", "generate_tests", "planning", "run_external_validation"}:
                owner = "build"
            deps = [str(dep) for dep in (task.get("depends_on") or []) if str(dep) in previous_ids]
            previous_ids.add(task_id)
            acceptance = task.get("acceptance") or task.get("acceptance_criteria") or []
            if isinstance(acceptance, str):
                acceptance = [acceptance]
            acceptance = [str(item).strip() for item in acceptance if str(item).strip()]
            if not acceptance:
                acceptance = ["This task satisfies its part of the user requirement."]
            task_deliverables = self._normalize_string_list(task.get("deliverables"))
            task_deliverable_set = self._normalize_string_list(task.get("deliverable_set"))
            tasks.append(
                {
                    "id": task_id,
                    "title": str(task.get("title") or task_id).strip(),
                    "owner": owner,
                    "depends_on": deps,
                    "allowed_write_paths": task.get("allowed_write_paths") or self._allowed_write_paths(project_dir),
                    "deliverables": task_deliverables,
                    "deliverable_set": task_deliverable_set,
                    "acceptance": acceptance[:30],
                    "source": str(task.get("source") or "adaptive_task_prompt_generator"),
                }
            )
        normalized["deliverables"] = self._normalize_string_list(normalized.get("deliverables"))
        normalized["tasks"] = tasks[:20] or self._fallback_manifest(requirement, project_dir)["tasks"]
        return normalized

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if isinstance(value, str):
            raw = [value]
        elif isinstance(value, list):
            raw = value
        else:
            raw = []
        items: list[str] = []
        for item in raw:
            text = str(item or "").strip()
            if text and text not in items:
                items.append(text)
        return items[:40]

    def _write_outputs(
        self,
        run: dict[str, Any],
        output_dir: Path,
        project_dir: Path,
        manifest: dict[str, Any],
        instance: dict[str, Any],
        task_findings: list[str],
        workflow_findings: list[str],
        workflow_spec: dict[str, Any],
        thinking_level: str,
        architecture_contract: dict[str, Any],
    ) -> None:
        write_text(output_dir / "architecture-contract.json", json.dumps(architecture_contract, indent=2, ensure_ascii=False))
        write_text(output_dir / "architecture-contract.md", self._render_architecture_contract_markdown(architecture_contract, thinking_level))
        write_text(output_dir / "workflow-spec.json", json.dumps(workflow_spec, indent=2, ensure_ascii=False))
        write_text(output_dir / "workflow-spec.md", self._render_workflow_spec_markdown(workflow_spec))
        write_text(output_dir / "workflow-decision-log.md", self._initial_decision_log(workflow_spec))
        write_text(output_dir / "task-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_text(output_dir / "generated-workflow-instance.json", json.dumps(instance, indent=2, ensure_ascii=False))
        write_text(output_dir / "workflow-instance-validation.md", orchestrator.render_validation_markdown(task_findings, workflow_findings))
        write_text(output_dir / "workflow-run-trace.md", orchestrator.render_run_trace(instance))
        write_text(output_dir / "task-manifest.md", self.render_manifest_markdown(manifest))
        self._write_task_prompts(run, output_dir, project_dir, manifest, thinking_level)

    def _build_architecture_contract(self, run: dict[str, Any], output_dir: Path, project_dir: Path, requirement: str) -> dict[str, Any]:
        project_index_path = output_dir / "project-index.md"
        project_index = read_text(project_index_path)
        if not project_index.strip():
            project_index = render_project_index_markdown(project_dir)
            write_text(project_index_path, project_index)
        instructions = orchestrator.extract_user_instructions(requirement, project_dir)
        contract = orchestrator.build_architecture_contract(project_dir, project_index, instructions)
        existing_architecture = read_text(project_dir / "architecture.md") or read_text(output_dir / "architecture.md")
        top_level = contract.get("top_level_entries") or []
        preferred_roots = contract.get("preferred_roots") or []
        extension_points = self._detect_extension_points(project_dir, top_level, preferred_roots)
        forbidden_parallel_changes = [
            "Do not create a second workflow runner, second chat runner, or duplicate orchestration service when an existing runtime module can be extended.",
            "Do not bypass existing config/service layers; extend the existing service or renderer responsible for the behavior.",
            "Do not introduce unrelated top-level folders, alternate package roots, or duplicate frontend state stores.",
            "Do not replace existing public APIs or data flow unless the current task explicitly requires a migration.",
        ]
        contract.update(
            {
                "kind": "adaptive_architecture_contract",
                "existing_architecture_excerpt": existing_architecture[:8000],
                "extension_points": extension_points,
                "forbidden_parallel_changes": forbidden_parallel_changes,
                "required_task_behavior": [
                    "Before editing, identify the existing module, file, or extension point that already owns the behavior.",
                    "Prefer minimal edits to existing files over creating new parallel files.",
                    "Preserve existing naming, API shape, state flow, and test style unless the task explicitly requires changing them.",
                    "After editing, record an Architecture Delta Summary describing changed files and why they fit the existing architecture.",
                ],
            }
        )
        return contract

    @staticmethod
    def _detect_extension_points(project_dir: Path, top_level: list[str], preferred_roots: list[str]) -> list[str]:
        points: list[str] = []
        if "app" in top_level:
            points.append("Backend/runtime changes should usually extend files under app/ before creating new backend roots.")
        if "static" in top_level:
            points.append("Frontend UI changes should usually extend static/js modules and existing static/*.html pages.")
        if "tests" in top_level:
            points.append("Tests should follow the existing tests/ layout and naming style.")
        if "data" in top_level:
            points.append("Workflow asset/config changes should usually extend existing files under data/ai-workflow when present.")
        if not points and preferred_roots:
            points.append("Use the preferred existing roots first: " + ", ".join(preferred_roots) + ".")
        if not points:
            points.append("Inspect existing files first and extend the dominant layout instead of inventing a new one.")
        return points

    def _render_architecture_contract_markdown(self, contract: dict[str, Any], thinking_level: str) -> str:
        lines = [
            "# Adaptive Architecture Contract",
            "",
            "Status: READY",
            f"Thinking: {thinking_label(thinking_level)} (`{thinking_level}`)",
            "",
            "## Purpose",
            "- Keep Adaptive Auto Workflow coding tasks aligned with the existing project architecture.",
            "- Every internal task prompt must treat this contract as a hard constraint before editing files.",
            "",
            "## Preferred Extension Points",
        ]
        for item in contract.get("extension_points") or []:
            lines.append(f"- {item}")
        lines.extend(["", "## Architecture Rules"])
        for item in contract.get("rules") or []:
            lines.append(f"- {item}")
        lines.extend(["", "## Forbidden Parallel Changes"])
        for item in contract.get("forbidden_parallel_changes") or []:
            lines.append(f"- {item}")
        lines.extend(["", "## Required Task Behavior"])
        for item in contract.get("required_task_behavior") or []:
            lines.append(f"- {item}")
        if str(contract.get("existing_architecture_excerpt") or "").strip():
            lines.extend(["", "## Existing architecture.md excerpt", "", str(contract.get("existing_architecture_excerpt")).strip()])
        lines.append("")
        return "\n".join(lines)

    def _build_workflow_spec(self, manifest: dict[str, Any], instance: dict[str, Any], thinking_level: str, architecture_contract: dict[str, Any]) -> dict[str, Any]:
        tasks = manifest.get("tasks") or []
        decision_options = ["continue", "repair_current_step"]
        if thinking_level in {"high", "extreme"}:
            decision_options.append("replan_remaining_steps")
        if thinking_level in {"high", "extreme"}:
            decision_options.append("architecture_conflict")
        if thinking_level == "extreme":
            decision_options.extend(["insert_new_step", "stop_and_ask_user", "finish"])
        return {
            "schema_version": 1,
            "kind": "adaptive_mini_workflow_spec",
            "status": "READY" if tasks else "EMPTY",
            "thinking_level": thinking_level,
            "thinking_label": thinking_label(thinking_level),
            "goal": manifest.get("goal") or "Complete the adaptive workflow request.",
            "visible_steps": [
                {"id": "generate_task_prompts", "phase": "spec", "goal": "Generate the internal Workflow Spec, Architecture Contract, task manifest, task prompts, and decision log.", "output": ["output/workflow-spec.json", "output/architecture-contract.json", "output/architecture-contract.md", "output/task-manifest.json", "output/task-prompts/TASK-xxx.md"]},
                {"id": "auto_generation", "phase": "execute_internal_loop", "goal": "Run the task prompt loop inside one visible workflow step.", "output": ["project_files", "output/tasks/TASK-xxx/review.md", "output/workflow-decision-log.md"]},
                {"id": "ai_review", "phase": "review", "goal": "Review the completed project change against the requirement and internal task results.", "output": ["output/review.md"]},
                {"id": "run_external_validation", "phase": "acceptance", "goal": "Run the Adaptive Python Gate: configured validation script first, then pytest when tests exist, otherwise a skipped PASS.", "output": ["output/external-validation-result.md", "output/test-result.md"]},
            ],
            "internal_loop": {"mode": "Task → Validate → Architecture Review → Reflect → Decide", "completed_valid_tasks_are_immutable": True, "architecture_contract_required": True, "decision_options": decision_options, "default_next_action": "continue", "repair_scope": "current_task_only", "replan_scope": "remaining_tasks_only"},
            "task_steps": [self._workflow_task_step(task, index=index, total=len(tasks), thinking_level=thinking_level) for index, task in enumerate(tasks, start=1)],
            "architecture_contract": {"artifact_json": "output/architecture-contract.json", "artifact_md": "output/architecture-contract.md", "rules": architecture_contract.get("rules", []), "preferred_roots": architecture_contract.get("preferred_roots", []), "extension_points": architecture_contract.get("extension_points", [])},
            "artifacts": {"task_manifest": "output/task-manifest.json", "architecture_contract": "output/architecture-contract.json", "workflow_instance": "output/generated-workflow-instance.json", "decision_log": "output/workflow-decision-log.md", "run_trace": "output/workflow-run-trace.md"},
            "compiled_instance_step_count": len(instance.get("steps") or []),
        }

    def _workflow_task_step(self, task: dict[str, Any], *, index: int, total: int, thinking_level: str) -> dict[str, Any]:
        task_id = str(task.get("id") or f"TASK-{index:03d}")
        checklist = [
            "Confirm this task is the smallest useful slice of the user requirement.",
            "Check dependencies and preserve outputs from completed valid tasks.",
            "Identify the existing module, renderer, service, or extension point that already owns this behavior.",
            "Prefer modifying existing files over creating new parallel architecture.",
            "Identify the files that should change and keep writes inside the project path.",
            "Verify acceptance criteria can be checked by tests, review, or external validation.",
        ]
        if thinking_level in {"high", "extreme"}:
            checklist.extend([
                "Before finishing, identify likely failure modes such as wrong path, missing import, test/production mixing, or architecture drift.",
                "Check that the change reuses existing data flow, naming, and extension points instead of duplicating them.",
                "Choose the smallest safe repair when validation feedback is available.",
            ])
        if thinking_level == "extreme":
            checklist.extend([
                "Internally decide whether later remaining tasks are still valid after this task output.",
                "If this task cannot fit the existing architecture, treat it as an architecture_conflict instead of inventing a second architecture.",
                "Only suggest replanning remaining tasks if the current result invalidates their inputs or scope.",
            ])
        return {
            "id": task_id,
            "name": str(task.get("title") or task_id),
            "type": "build" if task.get("owner") != "generate_tests" else "test",
            "goal": str(task.get("title") or task_id),
            "input": ["user_requirement", "project_files", *[str(dep) for dep in task.get("depends_on") or []]],
            "output": [f"output/tasks/{task_id}/", "project_files"],
            "validation_rules": task.get("acceptance") or ["Task satisfies its part of the user requirement."],
            "thinking_checklist": checklist,
            "retry_strategy": {"max_retry": 3, "repair_scope": "current_task_only"},
        }

    def _render_workflow_spec_markdown(self, spec: dict[str, Any]) -> str:
        lines = ["# Adaptive Mini Workflow Spec", "", f"Status: {spec.get('status')}", f"Thinking: {spec.get('thinking_label')} (`{spec.get('thinking_level')}`)", "", "## Goal", f"- {spec.get('goal')}", "", "## Visible Workflow Steps"]
        for step in spec.get("visible_steps") or []:
            outputs = ", ".join(step.get("output") or [])
            lines.append(f"- `{step.get('id')}` [{step.get('phase')}]: {step.get('goal')} → {outputs}")
        lines.extend(["", "## Internal Decision Loop", f"- Mode: {spec.get('internal_loop', {}).get('mode')}"])
        lines.append(f"- Decision options: {', '.join(spec.get('internal_loop', {}).get('decision_options') or [])}")
        architecture = spec.get("architecture_contract") or {}
        lines.extend(["", "## Architecture Contract", f"- JSON: {architecture.get('artifact_json')}", f"- Markdown: {architecture.get('artifact_md')}"])
        for point in architecture.get("extension_points") or []:
            lines.append(f"- Extension point: {point}")
        lines.extend(["", "## Internal Task Steps"])
        for step in spec.get("task_steps") or []:
            lines.append(f"- `{step.get('id')}`: {step.get('goal')}")
        lines.append("")
        return "\n".join(lines)

    def _initial_decision_log(self, spec: dict[str, Any]) -> str:
        return "\n".join(["# Adaptive Workflow Decision Log", "", "Status: READY", f"Thinking: {spec.get('thinking_label')} (`{spec.get('thinking_level')}`)", "", f"- PLANNED: generated internal Workflow Spec with {len(spec.get('task_steps') or [])} task(s).", "- PLANNED: generated Architecture Contract at output/architecture-contract.md.", f"- DECISION OPTIONS: {', '.join(spec.get('internal_loop', {}).get('decision_options') or [])}", ""])

    def render_manifest_markdown(self, manifest: dict[str, Any]) -> str:
        tasks = manifest.get("tasks") or []
        lines = [
            "# Adaptive Task Manifest",
            "",
            "Status: READY" if tasks else "Status: EMPTY",
            "",
            "## Purpose",
            "- Generated by the Adaptive Generate Task Prompts step.",
            "- The visible workflow remains fixed; Python uses this manifest to run a task prompt loop.",
            "- output/workflow-spec.json is the internal Mini Workflow Spec used by the Adaptive loop.",
            "- output/architecture-contract.md is injected into each internal task prompt to prevent architecture drift.",
            "- AI may propose task content, but Python controls execution, validation, retry, and project isolation.",
            "",
            "## Small Task Order",
        ]
        for index, task in enumerate(tasks, start=1):
            lines.append(f"{index}. {task.get('id')} [owner={task.get('owner', 'build')}]: {task.get('title')}")
        if manifest.get("deliverables"):
            lines.extend(["", "## Deliverable Coverage Contract"])
            for item in manifest.get("deliverables") or []:
                lines.append(f"- `{item}`")
        lines.extend(["", "## Prompt Files"])
        for task in tasks:
            lines.append(f"- output/task-prompts/{task.get('id')}.md")
        lines.extend(["", "## Final Acceptance", "- Run generated tests or the Adaptive Python Gate when available.", "- Run external validation when configured.", "- Every requested deliverable must have implementation traceability and verification evidence.", "- Repair uses task-scoped failure feedback before retrying the failed task.", ""])
        return "\n".join(lines)

    def _write_task_prompts(self, run: dict[str, Any], output_dir: Path, project_dir: Path, manifest: dict[str, Any], thinking_level: str) -> None:
        prompt_dir = output_dir / "task-prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        task_dir = output_dir / "todos"
        task_dir.mkdir(parents=True, exist_ok=True)
        existing = {path.name for path in prompt_dir.glob("TASK-*.md")}
        expected: set[str] = set()
        tasks = manifest.get("tasks") or []
        total = len(tasks)
        for index, task in enumerate(tasks, start=1):
            task_id = str(task.get("id") or f"TASK-{index:03d}")
            filename = f"{task_id}.md"
            expected.add(filename)
            prompt = self._render_task_prompt(run, project_dir, manifest, task, index=index, total=total, thinking_level=thinking_level)
            write_text(prompt_dir / filename, prompt)
            write_text(task_dir / filename, self._render_task_todo(manifest, task, index=index, total=total, thinking_level=thinking_level))
        for stale in existing - expected:
            path = prompt_dir / stale
            if path.is_file():
                path.unlink()
        write_text(task_dir / "INDEX.md", "# Adaptive Task Todo Index\n\nStatus: READY\n\n" + "\n".join(f"- output/todos/{task.get('id')}.md" for task in tasks) + "\n")

    def _render_task_prompt(self, run: dict[str, Any], project_dir: Path, manifest: dict[str, Any], task: dict[str, Any], *, index: int, total: int, thinking_level: str) -> str:
        acceptance = "\n".join(f"- {item}" for item in task.get("acceptance") or [])
        deps = ", ".join(task.get("depends_on") or []) or "None"
        deliverables = self._render_deliverable_block(task, manifest)
        architecture_contract = read_text(Path(run["workspace"]) / "output" / "architecture-contract.md")
        architecture_rule = self._architecture_preservation_rule(thinking_level)
        return f"""# Adaptive Task Prompt: {task.get('id')} — {task.get('title')}

Status: READY

## User Requirement
{manifest.get('goal')}

## Current Task
- ID: {task.get('id')}
- Index: {index}/{total}
- Title: {task.get('title')}
- Depends on: {deps}

## Acceptance Criteria
{acceptance or '- The task satisfies its part of the user requirement.'}

## Deliverable Coverage Contract
{deliverables}

## Project Context
{project_profile(project_dir)}

Visible files:
{project_overview(project_dir, limit=80)}

## Architecture Contract
{architecture_contract.strip() or '- No explicit architecture contract was generated; inspect the project and preserve the dominant existing layout.'}

## Architecture Preservation Rule
{architecture_rule}

## Thinking Level
- Effective level: {thinking_label(thinking_level)} (`{thinking_level}`)
{render_thinking_guidance(thinking_level, step_key="auto_generation", workflow_id="adaptive-auto-workflow") or "- No extra thinking guidance is injected for this task."}

## Internal Workflow Spec Gate
- Treat this task as an internal Workflow Spec step: Task → Validate → Reflect → Decide.
- Default decision after a valid task is `continue`.
- Prefer `repair_current_step` for local validation failures.
- Only consider `replan_remaining_steps` when the current result makes later internal tasks obsolete.
- Completed valid task outputs should remain immutable.

## Work Rules
- Complete only this task and already-required dependencies; do not proactively implement future task prompts.
- Before editing, name the existing module/extension point that owns the behavior and reuse it. Do not create a parallel runner, service, renderer, state store, API path, or top-level framework folder unless the current task explicitly requires it.
- Use Qwen/OpenCode file edit/write tools to modify files directly. If file tools are unavailable, output complete project files as `FILE: path`, `CONTENT:`, `END_FILE` blocks.
- Do not output standalone code fences. Every created or modified file must be represented by a direct edit or by a `FILE/CONTENT/END_FILE` block.
- In file block fallback, `FILE:` must contain only a relative file path, not prose, comments, code, `CONTENT`, or placeholders.
- Do not return explanations, placeholders, simulated workflow code, or repair helper functions instead of project files.
- Include focused tests or test files when this task changes executable behavior and the project can run tests.
- For every listed deliverable, include a traceability label in code comments/docstrings, test case names/ids, validation data, or a small coverage map so the workflow can verify coverage without domain-specific hard-coding.
- Keep production code and tests separate.
- Do not hard-code sample outputs, validator internals, or a single example input.
- Keep writes inside the selected Project path only. Reading external files for context is allowed when needed.
- Never write `.git`, `.qwen`, `opencode.json`, `.ai-workflow`, `.qwen-workflow`, absolute paths, or parent-directory paths.
- Do not modify validation scripts unless the user explicitly asked to modify the validator itself.

## Review Gate For This Task
- After making changes, review your own output against the User Requirement and Acceptance Criteria.
- Check whether the changed files are real project artifacts, not prose-only summaries.
- Check that production code and tests are separated when tests are generated.
- Check that imports, file paths, and entry points are plausible for the current project.
- Check whether focused tests, generated tests, or external validation can verify every listed deliverable.
- Check deliverable coverage: every requested item appears in implementation or verification traceability evidence.
- Check architecture alignment: existing module reused, no parallel duplicate architecture, no unnecessary top-level folder.
- If confidence is below 0.75, repair the implementation before finishing.
- In the final summary, include `Review confidence: <0.00-1.00>` and one sentence explaining the remaining risk or `No known remaining risk`.
""".strip() + "\n"

    @staticmethod
    def _render_deliverable_block(task: dict[str, Any], manifest: dict[str, Any]) -> str:
        current = [str(item) for item in task.get("deliverables") or [] if str(item).strip()]
        full = [str(item) for item in (task.get("deliverable_set") or manifest.get("deliverables") or []) if str(item).strip()]
        lines: list[str] = []
        if full:
            lines.append("Full requested deliverable set:")
            lines.extend(f"- `{item}`" for item in full)
        if current:
            if lines:
                lines.append("")
            lines.append("Current task deliverables that must be implemented or verified now:")
            lines.extend(f"- `{item}`" for item in current)
        if not lines:
            return "- No explicit itemized deliverable list was extracted; cover the full User Requirement."
        lines.extend(
            [
                "",
                "Traceability rule: preserve these exact labels in comments, docstrings, test names/ids, validation data, or a coverage map in the changed project artifacts.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _architecture_preservation_rule(thinking_level: str) -> str:
        if thinking_level == "none":
            return "- Basic rule: preserve the existing project layout and avoid unrelated new architecture."
        lines = [
            "- Identify the existing file/module/service/renderer that already owns the behavior before editing.",
            "- Prefer minimal changes to existing files over adding new parallel files.",
            "- Preserve naming style, imports, API shape, data flow, and test style.",
            "- New helper files are allowed only when they fit the existing folder/module pattern.",
        ]
        if thinking_level in {"high", "extreme"}:
            lines.extend(
                [
                    "- Do not duplicate runners, workflow engines, chat handlers, frontend state stores, service layers, validators, or config loaders.",
                    "- If you add a new file, explain why no existing extension point was sufficient in the Architecture Delta Summary.",
                    "- Treat architecture drift as a validation failure and repair the current task instead of continuing.",
                ]
            )
        if thinking_level == "extreme":
            lines.extend(
                [
                    "- Before finishing, internally decide whether the remaining internal tasks still fit the Architecture Contract.",
                    "- If the task cannot be completed without breaking the contract, mark the risk as high and choose architecture_conflict in the decision reasoning.",
                ]
            )
        return "\n".join(lines)

    def _render_task_todo(self, manifest: dict[str, Any], task: dict[str, Any], *, index: int, total: int, thinking_level: str) -> str:
        acceptance = "\n".join(f"  - {item}" for item in task.get("acceptance") or [])
        deps = ", ".join(task.get("depends_on") or []) or "None"
        deliverables = "\n".join(f"  - `{item}`" for item in task.get("deliverables") or []) or "  - Full user requirement"
        return f"""# {task.get('id')}: {task.get('title')}

Status: READY

## Execution Scope
- Task ID: {task.get('id')}
- Task index: {index}/{total}
- Owner step: {task.get('owner', 'build')}
- Depends on: {deps}
- Thinking level: {thinking_label(thinking_level)} (`{thinking_level}`)

## Requirement Slice
- Full requirement: {manifest.get('goal')}
- Current task: {task.get('title')}

## Deliverables
{deliverables}

## Acceptance Criteria
{acceptance or '  - The task satisfies its part of the user requirement.'}

## Hard Rules
- Use the generated task prompt as the active task scope.
- Build output may include production files and focused tests because Adaptive Auto Workflow is an all-in-one task loop.
- Do not implement unrelated future tasks unless needed as a dependency.
- Python review, automated tests, and external validation decide completion.
""".strip() + "\n"

    def _extract_independent_units(self, requirement: str) -> list[str]:
        text = (requirement or "").strip()
        if not text:
            return []
        # Prefer the concrete object list after the last create/implement verb.
        # The verb list describes generic development actions only; grouping later
        # is based on structural similarity of the extracted items, not domains.
        verb_pattern = re.compile(r"建立|實作|新增|製作|產生|create|implement|add|build|generate", flags=re.I)
        matches = list(verb_pattern.finditer(text))
        candidate = text[matches[-1].end():] if matches else text
        candidate = re.sub(r"^(?:一個|一份|the|a|an)\s+", "", candidate.strip(), flags=re.I)
        raw_parts = re.split(r"\s*(?:\+|、|，|,|；|;|以及|和|與|跟|\band\b)\s*", candidate)
        units: list[str] = []
        for part in raw_parts:
            item = re.sub(r"\s+", " ", part.strip(" .。\n\t"))
            if not item:
                continue
            # Drop very broad trailing qualifiers that are better handled by
            # acceptance/review, not as separate item tasks.
            if re.fullmatch(r"(?:測試|驗證|文件|整合|test|tests|validation|docs?|integration)", item, re.I):
                continue
            if len(item) > 80:
                continue
            if item not in units:
                units.append(item)
        return units if len(units) >= 2 else []

    @classmethod
    def _should_group_units(cls, units: list[str]) -> bool:
        if len(units) <= 12:
            return False
        normalized = [cls._normalize_unit_for_similarity(unit) for unit in units if unit.strip()]
        if len(normalized) <= 12:
            return False
        return (
            cls._common_suffix_length(normalized) >= 2
            or cls._common_prefix_length(normalized) >= 2
            or cls._common_substring_length(normalized) >= 2
            or cls._common_tail_token(normalized)
            or cls._common_head_token(normalized)
        )

    @staticmethod
    def _normalize_unit_for_similarity(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _common_suffix_length(values: list[str]) -> int:
        if not values:
            return 0
        suffix = values[0]
        for value in values[1:]:
            index = 0
            max_len = min(len(suffix), len(value))
            while index < max_len and suffix[-1 - index] == value[-1 - index]:
                index += 1
            suffix = suffix[len(suffix) - index :] if index else ""
            if not suffix:
                break
        return len(suffix.strip())

    @staticmethod
    def _common_prefix_length(values: list[str]) -> int:
        if not values:
            return 0
        prefix = values[0]
        for value in values[1:]:
            index = 0
            max_len = min(len(prefix), len(value))
            while index < max_len and prefix[index] == value[index]:
                index += 1
            prefix = prefix[:index]
            if not prefix:
                break
        return len(prefix.strip())


    @staticmethod
    def _common_substring_length(values: list[str]) -> int:
        if not values:
            return 0
        shortest = min(values, key=len)
        best = 0
        for start in range(len(shortest)):
            for end in range(start + 2, len(shortest) + 1):
                candidate = shortest[start:end].strip()
                if len(candidate) <= best:
                    continue
                if candidate and all(candidate in value for value in values):
                    best = len(candidate)
        return best

    @staticmethod
    def _common_tail_token(values: list[str]) -> bool:
        token_lists = [re.findall(r"[a-z0-9_]+", value) for value in values]
        if not token_lists or any(not tokens for tokens in token_lists):
            return False
        tail = token_lists[0][-1]
        return len(tail) >= 3 and all(tokens[-1] == tail for tokens in token_lists[1:])

    @staticmethod
    def _common_head_token(values: list[str]) -> bool:
        token_lists = [re.findall(r"[a-z0-9_]+", value) for value in values]
        if not token_lists or any(not tokens for tokens in token_lists):
            return False
        head = token_lists[0][0]
        return len(head) >= 3 and all(tokens[0] == head for tokens in token_lists[1:])

    def _allowed_write_paths(self, project_dir: Path) -> list[str]:
        roots = []
        for name in ["app", "src", "lib", "static", "data", "docs", "tests"]:
            if (project_dir / name).exists():
                roots.append(f"{name}/")
        return roots or ["./"]
