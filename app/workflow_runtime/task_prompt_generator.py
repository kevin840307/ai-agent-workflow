from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.auto_workflow import orchestrator
from app.core.paths import read_text, write_text
from app.runtime_modules.files import project_overview, project_profile


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
        self._write_outputs(run, output_dir, project_dir, manifest, instance, findings, workflow_findings)
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
                    "acceptance": [
                        f"`{unit}` is implemented as a reusable project artifact.",
                        f"Focused tests or validation evidence cover `{unit}`.",
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
                    "acceptance": [
                        "All item-level deliverables are exposed through one coherent project interface or artifact set.",
                        "Final tests or external validation can verify the full user request.",
                    ],
                    "source": "adaptive_requirement",
                }
            )
        return {
            "status": "READY",
            "schema_version": 1,
            "goal": requirement or "Complete the requested adaptive task.",
            "tasks": tasks,
            "final_acceptance": {
                "automated_tests_required": True,
                "external_validation_required_when_configured": True,
                "verifier_report_required": False,
            },
        }

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
            tasks.append(
                {
                    "id": task_id,
                    "title": str(task.get("title") or task_id).strip(),
                    "owner": owner,
                    "depends_on": deps,
                    "allowed_write_paths": task.get("allowed_write_paths") or self._allowed_write_paths(project_dir),
                    "acceptance": acceptance[:8],
                    "source": str(task.get("source") or "adaptive_task_prompt_generator"),
                }
            )
        normalized["tasks"] = tasks[:20] or self._fallback_manifest(requirement, project_dir)["tasks"]
        return normalized

    def _write_outputs(
        self,
        run: dict[str, Any],
        output_dir: Path,
        project_dir: Path,
        manifest: dict[str, Any],
        instance: dict[str, Any],
        task_findings: list[str],
        workflow_findings: list[str],
    ) -> None:
        write_text(output_dir / "task-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        write_text(output_dir / "generated-workflow-instance.json", json.dumps(instance, indent=2, ensure_ascii=False))
        write_text(output_dir / "workflow-instance-validation.md", orchestrator.render_validation_markdown(task_findings, workflow_findings))
        write_text(output_dir / "workflow-run-trace.md", orchestrator.render_run_trace(instance))
        write_text(output_dir / "task-manifest.md", self.render_manifest_markdown(manifest))
        self._write_task_prompts(run, output_dir, project_dir, manifest)

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
            "- AI may propose task content, but Python controls execution, validation, retry, and project isolation.",
            "",
            "## Small Task Order",
        ]
        for index, task in enumerate(tasks, start=1):
            lines.append(f"{index}. {task.get('id')} [owner={task.get('owner', 'build')}]: {task.get('title')}")
        lines.extend(["", "## Prompt Files"])
        for task in tasks:
            lines.append(f"- output/task-prompts/{task.get('id')}.md")
        lines.extend(["", "## Final Acceptance", "- Run generated tests when available.", "- Run external validation when configured; otherwise record a skipped PASS.", "- Repair uses task-scoped failure feedback before retrying the failed task.", ""])
        return "\n".join(lines)

    def _write_task_prompts(self, run: dict[str, Any], output_dir: Path, project_dir: Path, manifest: dict[str, Any]) -> None:
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
            prompt = self._render_task_prompt(run, project_dir, manifest, task, index=index, total=total)
            write_text(prompt_dir / filename, prompt)
            write_text(task_dir / filename, self._render_task_todo(manifest, task, index=index, total=total))
        for stale in existing - expected:
            path = prompt_dir / stale
            if path.is_file():
                path.unlink()
        write_text(task_dir / "INDEX.md", "# Adaptive Task Todo Index\n\nStatus: READY\n\n" + "\n".join(f"- output/todos/{task.get('id')}.md" for task in tasks) + "\n")

    def _render_task_prompt(self, run: dict[str, Any], project_dir: Path, manifest: dict[str, Any], task: dict[str, Any], *, index: int, total: int) -> str:
        acceptance = "\n".join(f"- {item}" for item in task.get("acceptance") or [])
        deps = ", ".join(task.get("depends_on") or []) or "None"
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

## Project Context
{project_profile(project_dir)}

Visible files:
{project_overview(project_dir, limit=80)}

## Work Rules
- Complete only this task and already-required dependencies; do not proactively implement future task prompts.
- Use Qwen/OpenCode file edit/write tools to modify files directly. If file tools are unavailable, output complete project files as `FILE: path`, `CONTENT:`, `END_FILE` blocks.
- Do not output standalone code fences. Every created or modified file must be represented by a direct edit or by a `FILE/CONTENT/END_FILE` block.
- In file block fallback, `FILE:` must contain only a relative file path, not prose, comments, code, `CONTENT`, or placeholders.
- Do not return explanations, placeholders, simulated workflow code, or repair helper functions instead of project files.
- Include focused tests or test files when this task is testable.
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
- Check whether focused tests or external validation can verify this task.
- If confidence is below 0.75, repair the implementation before finishing.
- In the final summary, include `Review confidence: <0.00-1.00>` and one sentence explaining the remaining risk or `No known remaining risk`.
""".strip() + "\n"

    def _render_task_todo(self, manifest: dict[str, Any], task: dict[str, Any], *, index: int, total: int) -> str:
        acceptance = "\n".join(f"  - {item}" for item in task.get("acceptance") or [])
        deps = ", ".join(task.get("depends_on") or []) or "None"
        return f"""# {task.get('id')}: {task.get('title')}

Status: READY

## Execution Scope
- Task ID: {task.get('id')}
- Task index: {index}/{total}
- Owner step: {task.get('owner', 'build')}
- Depends on: {deps}

## Requirement Slice
- Full requirement: {manifest.get('goal')}
- Current task: {task.get('title')}

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
        # Prefer the concrete object list after common create/implement verbs; this
        # is language-neutral enough for broad development requests and avoids
        # hard-coding particular domains such as sorting algorithms.
        match = re.search(r"(?:建立|實作|新增|製作|產生|create|implement|add|build|generate)\s*(.+)$", text, flags=re.I)
        candidate = match.group(1) if match else text
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

    @staticmethod
    def _should_group_units(units: list[str]) -> bool:
        return False

    def _allowed_write_paths(self, project_dir: Path) -> list[str]:
        roots = []
        for name in ["app", "src", "lib", "static", "data", "docs", "tests"]:
            if (project_dir / name).exists():
                roots.append(f"{name}/")
        return roots or ["./"]
