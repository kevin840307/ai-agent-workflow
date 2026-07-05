from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import failure_feedback_for_step, project_overview, project_profile, render_project_index_markdown
from app.core.paths import AI_WORKFLOW_DIR, DEFAULT_SKILL_PATH, ROOT, SYSTEM_WORKFLOW_ID, WORKFLOW_BUNDLES_DIR, read_text, write_text
from app.runtime_modules.skills import load_skill_context
from app.services.workflow_asset_service import GLOBAL_ASSET_ROOT, PROJECT_ASSET_DIR
from app.auto_workflow import orchestrator
from app.workflow_runtime.thinking import render_thinking_guidance, step_thinking_level

from .questions import interaction_instruction
from .step_utils import bool_config


def workflow_prompt_path(name: str, run: dict[str, Any] | None = None) -> Path:
    workflow_folder = (run or {}).get("workflow_folder") or (run or {}).get("workflow_id") or SYSTEM_WORKFLOW_ID
    normalized = name.replace("\\", "/").lstrip("/")
    raw_path = Path(name).expanduser()
    if raw_path.is_absolute():
        return raw_path
    project_path = (run or {}).get("project_path")
    if normalized.startswith(f"{PROJECT_ASSET_DIR}/"):
        asset_rel = normalized[len(PROJECT_ASSET_DIR) + 1 :]
        if project_path:
            project_asset = Path(project_path) / PROJECT_ASSET_DIR / asset_rel
            if project_asset.exists():
                return project_asset
        return GLOBAL_ASSET_ROOT / asset_rel
    if normalized.startswith("steps/"):
        if project_path:
            project_asset = Path(project_path) / PROJECT_ASSET_DIR / normalized
            if project_asset.exists():
                return project_asset
        global_asset = GLOBAL_ASSET_ROOT / normalized
        if global_asset.exists():
            return global_asset
    if normalized.startswith("prompts/"):
        canonical = GLOBAL_ASSET_ROOT / "steps" / workflow_folder / Path(normalized).name
        if canonical.exists():
            return canonical
        return WORKFLOW_BUNDLES_DIR / workflow_folder / normalized
    canonical = GLOBAL_ASSET_ROOT / "steps" / workflow_folder / Path(normalized).name
    if canonical.exists():
        return canonical
    return WORKFLOW_BUNDLES_DIR / workflow_folder / "prompts" / normalized


def load_prompt(name: str, run: dict[str, Any] | None = None, **values: str) -> str:
    path = workflow_prompt_path(name, run)
    if not path.exists():
        raise WorkflowError(f"Prompt template missing in workflow bundle: {path}")
    template = read_text(path)
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


@dataclass(slots=True)
class PromptBuildResult:
    prompt: str
    prompt_template: str
    skill_files: list[Path]
    skill_context: str
    relative_prompt_path: str


class PromptBuilder:
    def build(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        *,
        allow_interaction: bool | None,
        agent_name: str = "qwen",
    ) -> PromptBuildResult:
        output_dir = Path(run["workspace"]) / "output"
        input_dir = Path(run["workspace"]) / "input"
        project_dir = Path(run.get("project_path") or ROOT)
        step_record = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        step_config = step_record.get("config") or {}

        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        answers = read_text(input_dir / "answers.md")
        guidance = read_text(input_dir / "guidance.md")
        failure_feedback = failure_feedback_for_step(read_text(input_dir / "failure-feedback.md"), step_key)
        architecture = read_text(project_dir / "architecture.md") or read_text(output_dir / "architecture.md")
        profile = project_profile(project_dir)
        project_index_path = output_dir / "project-index.md"
        write_text(project_index_path, render_project_index_markdown(project_dir))

        skill_root = step_config.get("skillRoot") or run.get("skill_root") or str(DEFAULT_SKILL_PATH)
        skill_context, skill_files = load_skill_context(self._configured_skill_paths(step_config, str(skill_root), project_dir, run))

        values = self._template_values(
            run,
            output_dir,
            project_dir,
            requirement,
            architecture,
            profile,
            answers,
            guidance,
            failure_feedback,
            step_config,
            step_key=step_key,
        )
        inline_template = str(step_config.get("templateContent") or "")
        if inline_template.strip():
            prompt_template = inline_template
            prompt = self._render_template(inline_template, values)
        else:
            prompt_template = read_text(workflow_prompt_path(prompt_name, run))
            prompt = load_prompt(prompt_name, run=run, **values)

        command = str(step_config.get("command") or "").strip()
        if command and command != "custom" and not prompt.lstrip().startswith(command):
            prompt = f"{command}\n\n{prompt}"

        extra_context = self._extra_sources(step_config, run, project_dir, output_dir, prompt_name)
        if extra_context.strip():
            prompt = f"{prompt}\n\nAdditional workflow context from step.sources:\n\n{extra_context.strip()}\n"

        artifact_context = self._artifact_dependency_context(step_key, step_config, run, output_dir, prompt_template)
        if artifact_context.strip():
            prompt = (
                f"{prompt}\n\n"
                "Required workflow dependency context from previous artifacts. "
                "Use this as the source of truth and do not ignore it:\n\n"
                f"{artifact_context.strip()}\n"
            )

        if answers.strip() and "{{answers}}" not in prompt_template:
            prompt = f"{prompt}\n\nUser replies from previous workflow interaction:\n\n{answers.strip()}\n"
        if guidance.strip() and "{{guidance}}" not in prompt_template:
            prompt = f"{prompt}\n\nUser step guidance added during the workflow:\n\n{guidance.strip()}\n"
        if bool_config(step_config, "injectFailureFeedback", True):
            if (
                failure_feedback.strip()
                and "{{last_error}}" not in prompt_template
                and "{{failure_feedback}}" not in prompt_template
                and "{{current_task_failure_feedback}}" not in prompt_template
            ):
                prompt = (
                    f"{prompt}\n\n"
                    "Failure feedback from previous retry attempts. Fix these concrete errors before producing this step output:\n\n"
                    f"{failure_feedback.strip()}\n"
                )
        if architecture.strip() and step_key != "prepare_project" and "{{architecture}}" not in prompt_template:
            prompt = f"{prompt}\n\nCurrent project architecture context from architecture.md:\n\n{architecture.strip()}\n"
        if profile.strip() and step_key != "prepare_project" and "{{project_profile}}" not in prompt_template:
            prompt = f"{prompt}\n\nCurrent project profile inferred from existing files:\n\n{profile.strip()}\n"
        thinking_guidance = render_thinking_guidance(
            step_thinking_level(step_record, run),
            step_key=step_key,
            workflow_id=str(run.get("workflow_id") or ""),
        )
        if thinking_guidance.strip() and "{{thinking_guidance}}" not in prompt_template:
            prompt = f"{prompt}\n\n{thinking_guidance.strip()}\n"
        if allow_interaction is None:
            allow_interaction = bool(step_record.get("allow_interaction"))
        prompt = f"{prompt}\n\n{interaction_instruction(bool(allow_interaction))}"

        if skill_context.strip():
            selected = "\n".join(f"- {path}" for path in skill_files) if skill_files else f"- {skill_root}"
            prompt = self._wrap_with_agent_profile(prompt, f"{selected}\n\n{skill_context.strip()}", agent_name)
            write_text(Path(run["workspace"]) / "prompts" / "skill-context.md", skill_context)

        relative_prompt_path = f"prompts/{step_key}.md"
        write_text(Path(run["workspace"]) / "prompts" / f"{step_key}.md", prompt)
        return PromptBuildResult(
            prompt=prompt,
            prompt_template=prompt_template,
            skill_files=skill_files,
            skill_context=skill_context,
            relative_prompt_path=relative_prompt_path,
        )

    def _template_values(
        self,
        run: dict[str, Any],
        output_dir: Path,
        project_dir: Path,
        requirement: str,
        architecture: str,
        profile: str,
        answers: str,
        guidance: str,
        failure_feedback: str,
        step_config: dict[str, Any] | None = None,
        step_key: str = "",
    ) -> dict[str, str]:
        step_output_artifact = ""
        if step_config:
            step_output_artifact = str(step_config.get("outputFile") or step_config.get("filename") or "").strip()
        step_output = read_text(output_dir / step_output_artifact) if step_output_artifact else ""
        current_task = run.get("_current_task") or {}
        if not isinstance(current_task, dict):
            current_task = {}
        current_task_block = ""
        current_task_todo = ""
        current_task_prompt = ""
        current_task_failure_feedback = ""
        if current_task:
            current_task_block = "\n".join(
                [
                    f"Task ID: {current_task.get('id', '')}",
                    f"Task Title: {current_task.get('title', '')}",
                    f"Task Index: {current_task.get('index', '')}/{current_task.get('total', '')}",
                    f"Task Owner Step: {current_task.get('owner', '')}",
                    f"Task Phase: {current_task.get('phase', '')}",
                    f"Task TODO File: {current_task.get('todo_path', '')}",
                ]
            ).strip()
            task_id = str(current_task.get("id") or "").strip()
            safe_task_id = "".join(ch if ch.isalnum() or ch in {"_", ".", "-"} else "-" for ch in task_id)
            if safe_task_id:
                current_task_todo = read_text(output_dir / "todos" / f"{safe_task_id}.md")
                current_task_prompt = read_text(output_dir / "task-prompts" / f"{safe_task_id}.md")
                current_task_failure_feedback = self._current_task_failure_feedback(failure_feedback, task_id)
        effective_thinking_level = step_thinking_level({"key": step_key, "config": step_config or {}}, run)
        effective_thinking_guidance = render_thinking_guidance(
            effective_thinking_level,
            step_key=step_key,
            workflow_id=str(run.get("workflow_id") or ""),
        )
        return {
            "requirement": requirement,
            "architecture": architecture,
            "project_profile": profile,
            "project_index": read_text(output_dir / "project-index.md"),
            "project_python_import_map": self._project_python_import_map(project_dir),
            "request_intent": self._request_intent(run, requirement, project_dir),
            "user_instructions": self._user_instructions(requirement, project_dir),
            "architecture_contract": self._architecture_contract(run, requirement, project_dir, output_dir),
            "project_overview": project_overview(project_dir),
            "spec": read_text(output_dir / "spec.md"),
            "spec_review": read_text(output_dir / "spec-review.md"),
            "todo": read_text(output_dir / "todo.md"),
            "task_manifest": read_text(output_dir / "task-manifest.md"),
            "task_manifest_json": read_text(output_dir / "task-manifest.json"),
            "workflow_instance": read_text(output_dir / "generated-workflow-instance.json"),
            "workflow_spec": read_text(output_dir / "workflow-spec.md"),
            "workflow_spec_json": read_text(output_dir / "workflow-spec.json"),
            "workflow_instance_validation": read_text(output_dir / "workflow-instance-validation.md"),
            "workflow_run_trace": read_text(output_dir / "workflow-run-trace.md"),
            "workflow_decision_log": read_text(output_dir / "workflow-decision-log.md"),
            "thinking_level": effective_thinking_level,
            "thinking_guidance": effective_thinking_guidance,
            "current_task": current_task_block,
            "current_task_todo": current_task_todo,
            "current_task_prompt": current_task_prompt,
            "current_task_failure_feedback": current_task_failure_feedback,
            "current_task_file_context": self._current_task_file_context(output_dir, project_dir, current_task),
            "current_task_id": str(current_task.get("id") or ""),
            "current_task_title": str(current_task.get("title") or ""),
            "current_task_owner": str(current_task.get("owner") or ""),
            "current_task_index": str(current_task.get("index") or ""),
            "current_task_total": str(current_task.get("total") or ""),
            "todo_review": read_text(output_dir / "todo-review.md"),
            "test_plan": read_text(output_dir / "test-plan.md"),
            "reasoning": read_text(output_dir / "reasoning.md"),
            "build_reasoning": read_text(output_dir / "build-reasoning.md"),
            "test_result": read_text(output_dir / "test-result.md"),
            "external_validation_result": read_text(output_dir / "external-validation-result.md"),
            "build_result": read_text(output_dir / "build-result.md"),
            "auto_generation_result": read_text(output_dir / "auto-generation-result.md"),
            "python_gate_result": read_text(output_dir / "python-gate-result.md"),
            "verifier_report": read_text(output_dir / "verifier-report.json"),
            "diff_context": read_text(output_dir / "diff-context.md"),
            "diff_review": read_text(output_dir / "diff-review.md"),
            "final_review": read_text(output_dir / "final-review.md"),
            "raw_spec": read_text(output_dir / "spec.md"),
            "answers": answers,
            "guidance": guidance,
            "last_error": failure_feedback,
            "failure_feedback": failure_feedback,
            "latest_failure_feedback": self._latest_failure_feedback(failure_feedback),
            "step_output": step_output,
            "security_context": read_text(output_dir / "security-context.md"),
            "security_candidates": self._read_security_candidate_artifacts(output_dir),
            "security_candidate_scores": self._read_security_candidate_score_artifacts(output_dir),
            "security_findings": read_text(output_dir / "security-findings.md"),
            "security_report_score": read_text(output_dir / "security-report-score.md"),
            "project_path": str(run.get("project_path", "")),
            "workspace_path": str(run.get("workspace", "")),
            "validation_script": str(run.get("validation_script") or ""),
            "validation_script_content": self._validation_script_content(run, project_dir, include_content=step_key in {"run_external_validation", "python_gate"}),
            "fallback_validation_scripts": self._fallback_validation_scripts(run),
        }

    def _current_task_file_context(self, output_dir: Path, project_dir: Path, current_task: dict[str, Any]) -> str:
        task_id = str(current_task.get("id") or "").strip()
        try:
            current_index = int(current_task.get("index") or 0)
        except (TypeError, ValueError):
            current_index = 0
        if not task_id:
            return "No task-scoped project file context."
        task_output_root = output_dir / "tasks"
        if not task_output_root.exists():
            return "No previous task output files to preserve yet."

        candidate_paths: list[str] = []
        for task_dir in sorted(path for path in task_output_root.iterdir() if path.is_dir()):
            match = re.fullmatch(r"TASK-(\d{3})", task_dir.name)
            if not match:
                continue
            task_number = int(match.group(1))
            include_task = bool(current_index and task_number < current_index) or task_dir.name == task_id
            if not include_task:
                continue
            for artifact_name in ("build-result.md", "adaptive-generation-result.md"):
                artifact_path = task_dir / artifact_name
                for rel_path, _ in self._extract_file_blocks_for_context(read_text(artifact_path)):
                    if rel_path not in candidate_paths:
                        candidate_paths.append(rel_path)

        if not candidate_paths:
            return "No previous task output files to preserve yet."

        sections: list[str] = [
            "The following files already exist from completed or retried task outputs.",
            "When editing any of these paths, return the complete file content and preserve existing behavior unless the current task explicitly requires changing it.",
        ]
        shown = 0
        for rel_path in candidate_paths[:8]:
            safe_rel = rel_path.strip().strip("`").replace("\\", "/")
            if not safe_rel or safe_rel.startswith("/") or ".." in safe_rel.split("/"):
                continue
            path = project_dir / safe_rel
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError:
                continue
            if len(content) > 12000:
                content = content[:12000].rstrip() + "\n... <truncated>\n"
            sections.extend(["", f"### {safe_rel}", "```", content.rstrip(), "```"])
            shown += 1
        if shown == 0:
            return "No readable previous task output file content is available."
        if len(candidate_paths) > shown:
            sections.append(f"\nAdditional preserved files omitted from prompt: {len(candidate_paths) - shown}")
        return "\n".join(sections).strip()

    @staticmethod
    def _project_python_import_map(project_dir: Path) -> str:
        ignored_parts = {
            ".ai-workflow",
            ".git",
            ".pytest_cache",
            ".qwen",
            ".qwen-workflow",
            "__pycache__",
            "tests",
        }
        candidates: list[str] = []
        for path in sorted(project_dir.rglob("*.py")):
            try:
                rel = path.relative_to(project_dir)
            except ValueError:
                continue
            parts = rel.parts
            if any(part in ignored_parts for part in parts):
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            module_parts = list(parts)
            module_parts[-1] = path.stem
            if module_parts[-1] == "__init__":
                module_parts = module_parts[:-1]
            if not module_parts or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in module_parts):
                continue
            module_name = ".".join(module_parts)
            candidates.append(f"- `{rel.as_posix()}` -> `import {module_name}` or `from {module_name} import ...`")
        if not candidates:
            return "No importable project Python modules detected yet."
        return "\n".join(candidates[:80])

    @staticmethod
    def _extract_file_blocks_for_context(text: str) -> list[tuple[str, str]]:
        files: list[tuple[str, str]] = []
        pattern = re.compile(
            r"^FILE:\s*(?P<path>.+?)\s*\r?\n(?:CONTENT:\r?\n)?(?P<content>.*?)(?=^FILE:\s*|^END_FILE\s*$|\Z)",
            re.DOTALL | re.MULTILINE,
        )
        for match in pattern.finditer(text or ""):
            rel_path = match.group("path").strip().strip("`").replace("\\", "/")
            content = match.group("content")
            files.append((rel_path, content))
        return files

    def _current_task_failure_feedback(self, feedback: str, task_id: str) -> str:
        if not feedback.strip() or not task_id.strip():
            return "No failure feedback for this task yet."
        blocks = re.findall(
            r"^## Retry Feedback for .*?(?=^## Retry Feedback for |\Z)",
            feedback,
            flags=re.MULTILINE | re.DOTALL,
        )
        matches = []
        for block in blocks:
            if task_id in block or re.search(rf"\btask\s+{re.escape(task_id)}\b", block, flags=re.I):
                matches.append(block.strip())
        if not matches:
            return "No failure feedback for this task yet."
        # Keep only recent, task-scoped feedback.  Full run feedback can become
        # very large and may pull small/local models toward repairing the
        # workflow itself instead of implementing the current user task.
        joined = "\n\n".join(matches[-3:])
        return joined[-6000:]

    @staticmethod
    def _latest_failure_feedback(feedback: str) -> str:
        if not feedback.strip():
            return "No failure feedback yet."
        blocks = re.findall(
            r"^## Retry Feedback for .*?(?=^## Retry Feedback for |\Z)",
            feedback,
            flags=re.MULTILINE | re.DOTALL,
        )
        text = (blocks[-1] if blocks else feedback).strip()
        return text[-6000:] if len(text) > 6000 else text

    def _request_intent(self, run: dict[str, Any], requirement: str, project_dir: Path) -> str:
        intent = orchestrator.route_request(
            requirement,
            validation_script=str(run.get("validation_script") or ""),
            project_has_files=project_dir.exists() and any(project_dir.iterdir()),
        )
        return json.dumps(intent, indent=2, ensure_ascii=False)

    def _user_instructions(self, requirement: str, project_dir: Path) -> str:
        instructions = orchestrator.extract_user_instructions(requirement, project_dir)
        return json.dumps(instructions, indent=2, ensure_ascii=False)

    def _architecture_contract(self, run: dict[str, Any], requirement: str, project_dir: Path, output_dir: Path) -> str:
        instructions = orchestrator.extract_user_instructions(requirement, project_dir)
        project_index = read_text(output_dir / "project-index.md")
        contract = orchestrator.build_architecture_contract(project_dir, project_index, instructions)
        contract_path = output_dir / "architecture-contract.json"
        if not contract_path.exists():
            write_text(contract_path, json.dumps(contract, indent=2, ensure_ascii=False))
        return json.dumps(contract, indent=2, ensure_ascii=False)

    def _render_template(self, template: str, values: dict[str, str]) -> str:
        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered

    def _read_security_candidate_artifacts(self, output_dir: Path) -> str:
        blocks: list[str] = []
        for path in sorted(output_dir.glob("security-candidates-agent-*.md")):
            if path.name.endswith("-score.md"):
                continue
            text = read_text(path)
            if text.strip():
                blocks.append(f"### output/{path.name}\n\n{text.strip()}")
        return "\n\n".join(blocks)

    def _read_security_candidate_score_artifacts(self, output_dir: Path) -> str:
        blocks: list[str] = []
        for path in sorted(output_dir.glob("security-candidates-agent-*-score.md")):
            text = read_text(path)
            if text.strip():
                blocks.append(f"### output/{path.name}\n\n{text.strip()}")
        return "\n\n".join(blocks)

    def _fallback_validation_scripts(self, run: dict[str, Any]) -> str:
        for step in run.get("steps") or []:
            if step.get("key") not in {"run_external_validation", "python_gate"}:
                continue
            nested = step.get("config") if isinstance(step.get("config"), dict) else {}
            config = {**step, **nested}
            value = config.get("fallbackValidationScripts") or config.get("fallback_validation_scripts") or []
            if isinstance(value, str):
                items = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(value, list):
                items = [str(item).strip() for item in value if str(item).strip()]
            else:
                items = []
            return "\n".join(f"- `{item}`" for item in items) if items else "- None configured."
        return "- None configured."

    def _validation_script_content(self, run: dict[str, Any], project_dir: Path, *, include_content: bool = False) -> str:
        raw_path = str(run.get("validation_script") or "").strip()
        if not raw_path:
            return "No validation script was provided for this run."
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_dir / path
        if not path.exists() or not path.is_file():
            return f"Validation script not found at: {raw_path}"
        if not include_content:
            return (
                "A read-only external validation script is configured for this run.\n"
                f"- Script path: {path}\n"
                "- Treat it only as an external acceptance gate.\n"
                "- Do not modify it, copy it into production, or treat it as the requested deliverable.\n"
                "- If the gate fails, the workflow will pass stdout/stderr back as retry feedback."
            )
        text = read_text(path)
        header = (
            "READ-ONLY EXTERNAL VALIDATION SCRIPT. This file is outside the product scope unless the user explicitly asks to edit the validator.\n"
            "Use it only to understand acceptance behavior. Do not modify it, copy it into production, or treat it as the requested deliverable.\n\n"
        )
        if len(text) > 12000:
            return header + text[:12000] + "\n\n[validation script truncated]"
        return header + text

    def _artifact_dependency_context(
        self,
        step_key: str,
        step_config: dict[str, Any],
        run: dict[str, Any],
        output_dir: Path,
        prompt_template: str,
    ) -> str:
        artifacts = self._context_artifacts_for_step(step_key, step_config)
        if not artifacts:
            return ""
        placeholder_by_artifact = {
            "spec.md": "{{spec}}",
            "spec-review.md": "{{spec_review}}",
            "todo.md": "{{todo}}",
            "todo-review.md": "{{todo_review}}",
            "test-plan.md": "{{test_plan}}",
            "reasoning.md": "{{reasoning}}",
            "build-reasoning.md": "{{build_reasoning}}",
            "test-result.md": "{{test_result}}",
            "build-result.md": "{{build_result}}",
            "final-review.md": "{{final_review}}",
            "security-context.md": "{{security_context}}",
            "security-findings.md": "{{security_findings}}",
            "security-report-score.md": "{{security_report_score}}",
        }
        blocks: list[str] = []
        for artifact in artifacts:
            normalized = artifact.replace("\\", "/").lstrip("/")
            if normalized.startswith("output/"):
                normalized = normalized[len("output/") :]
            # Avoid duplicating large artifacts already explicitly embedded by the template.
            placeholder = placeholder_by_artifact.get(normalized)
            if placeholder and placeholder in prompt_template:
                continue
            text = self._read_artifact_source(run, output_dir, normalized)
            if text.strip():
                blocks.append(f"### output/{normalized}\n\n{text.strip()}")
        return "\n\n".join(blocks)

    def _context_artifacts_for_step(self, step_key: str, step_config: dict[str, Any]) -> list[str]:
        raw = step_config.get("contextArtifacts")
        if raw is None:
            raw = step_config.get("dependsOnArtifacts")
        if raw is None:
            raw = []
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        if not isinstance(raw, list):
            return []
        artifacts: list[str] = []
        for item in raw:
            value = str(item or "").strip().replace("\\", "/")
            if value and value not in artifacts:
                artifacts.append(value)
        return artifacts

    def _extra_sources(
        self,
        step_config: dict[str, Any],
        run: dict[str, Any],
        project_dir: Path,
        output_dir: Path,
        prompt_name: str,
    ) -> str:
        sources = step_config.get("sources") or []
        if not isinstance(sources, list):
            return ""
        blocks: list[str] = []
        for index, source in enumerate(sources, start=1):
            if not isinstance(source, dict):
                continue
            source_type = str(source.get("type") or "").strip()
            value = str(source.get("value") or "").strip()
            if not value:
                continue
            text = ""
            label = f"source {index}: {source_type} {value}"
            if source_type == "inline_prompt":
                text = value
            elif source_type == "command":
                # command is handled separately at the top of the prompt.
                continue
            elif source_type == "artifact":
                text = self._read_artifact_source(run, output_dir, value)
            elif source_type == "context_file":
                text = self._read_first_existing([project_dir / value, Path(run["workspace"]) / value, ROOT / value])
            elif source_type == "prompt_file":
                # Avoid duplicating the main template.
                normalized = value.replace("\\", "/").lstrip("/")
                current = prompt_name.replace("\\", "/").lstrip("/")
                if normalized == current or normalized == f"prompts/{current}":
                    continue
                text = read_text(workflow_prompt_path(value, run))
            elif source_type == "skill_path":
                # Skill files are loaded into the dedicated agent profile wrapper
                # so they do not get duplicated in generic source context.
                continue
            if text.strip():
                blocks.append(f"### {label}\n\n{text.strip()}")
        return "\n\n".join(blocks)

    def _configured_skill_paths(self, step_config: dict[str, Any], skill_root: str, project_dir: Path, run: dict[str, Any]) -> list[str]:
        raw_values: list[str] = []
        for key in ["skillPath", "skillPaths"]:
            raw = step_config.get(key)
            if isinstance(raw, str):
                raw_values.extend(part.strip() for part in raw.split(","))
            elif isinstance(raw, list):
                raw_values.extend(str(item or "").strip() for item in raw)
        for source in step_config.get("sources") or []:
            if not isinstance(source, dict):
                continue
            if str(source.get("type") or "").strip() == "skill_path":
                raw_values.append(str(source.get("value") or "").strip())

        paths: list[str] = []
        for value in raw_values:
            if not value:
                continue
            candidate = Path(value).expanduser()
            if candidate.is_absolute() or value.startswith("~/"):
                paths.append(str(candidate))
                continue
            if value.split("/", 1)[0] in {"steps", "contracts", "functions", "workflows"}:
                paths.append(str(AI_WORKFLOW_DIR / value))
                paths.append(str(project_dir / ".ai-workflow" / value))
                paths.append(str(project_dir / value))
                continue
            root = Path(skill_root).expanduser()
            if root.is_absolute() or skill_root.startswith("~/"):
                paths.append(str(root / value))
            else:
                workflow_folder = run.get("workflow_folder") or run.get("workflow_id") or SYSTEM_WORKFLOW_ID
                paths.append(str(WORKFLOW_BUNDLES_DIR / workflow_folder / root / value))
                paths.append(str(project_dir / root / value))
            paths.append(str(project_dir / value))
        return list(dict.fromkeys(paths))

    def _read_artifact_source(self, run: dict[str, Any], output_dir: Path, value: str) -> str:
        normalized = value.replace("\\", "/").lstrip("/")
        workspace = Path(run["workspace"])
        candidates = []
        if normalized.startswith("output/"):
            candidates.append(workspace / normalized)
            candidates.append(output_dir / normalized[len("output/") :])
        else:
            candidates.append(output_dir / normalized)
            candidates.append(workspace / normalized)
        return self._read_first_existing(candidates)

    def _read_first_existing(self, candidates: list[Path]) -> str:
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return read_text(candidate)
        return ""

    def _wrap_with_agent_profile(self, prompt: str, selected_skills: str, agent_name: str) -> str:
        if agent_name == "qwen":
            skill_header = (
                "Reference instruction files have been loaded as background methodology only. "
                "Use them for method and constraints, not as write targets or user requirements. "
                "When the workflow step asks for direct project edits, use the agent's file edit/write tools. "
                "Do not output JSON unless the task explicitly asks for JSON.\n\n"
                f"Reference files:\n{selected_skills}\n\n"
            )
        else:
            skill_header = (
                f"Reference instruction files have been loaded for the {agent_name} agent as background methodology only. "
                "Use them for method and constraints, not as write targets or user requirements. "
                "When the workflow step asks for direct project edits, use the agent's file edit/write tools. "
                "Do not output JSON unless the task explicitly asks for JSON.\n\n"
                f"Reference files:\n{selected_skills}\n\n"
            )
        return (
            f"{skill_header}"
            "Task follows. Output only the final artifact content requested by the task.\n\n"
            f"{prompt}\n\n"
            "Final reminder: output artifact content only, unless you need user input. "
            "Ask the user only under the strict Human interaction rule above; otherwise make reasonable assumptions and continue."
        )
