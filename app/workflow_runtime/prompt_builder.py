from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import failure_feedback_for_step, project_overview, project_profile, render_project_index_markdown
from app.core.paths import DEFAULT_SKILL_PATH, ROOT, SYSTEM_WORKFLOW_ID, WORKFLOW_BUNDLES_DIR, read_text, write_text
from app.runtime_modules.skills import load_skill_context
from app.services.workflow_asset_service import GLOBAL_ASSET_ROOT, PROJECT_ASSET_DIR

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
        architecture = read_text(project_dir / "architecture.md")
        profile = project_profile(project_dir)
        project_index_path = output_dir / "project-index.md"
        if not project_index_path.exists():
            write_text(project_index_path, render_project_index_markdown(project_dir))

        skill_root = step_config.get("skillRoot") or run.get("skill_root") or str(DEFAULT_SKILL_PATH)
        skill_context, skill_files = load_skill_context(self._configured_skill_paths(step_config, str(skill_root), project_dir, run))

        values = self._template_values(run, output_dir, project_dir, requirement, architecture, profile, answers, guidance, failure_feedback, step_config)
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
            if failure_feedback.strip() and "{{last_error}}" not in prompt_template and "{{failure_feedback}}" not in prompt_template:
                prompt = (
                    f"{prompt}\n\n"
                    "Failure feedback from previous retry attempts. Fix these concrete errors before producing this step output:\n\n"
                    f"{failure_feedback.strip()}\n"
                )
        if architecture.strip() and step_key != "prepare_project" and "{{architecture}}" not in prompt_template:
            prompt = f"{prompt}\n\nCurrent project architecture context from architecture.md:\n\n{architecture.strip()}\n"
        if profile.strip() and step_key != "prepare_project" and "{{project_profile}}" not in prompt_template:
            prompt = f"{prompt}\n\nCurrent project profile inferred from existing files:\n\n{profile.strip()}\n"
        if allow_interaction is None:
            allow_interaction = bool(step_record.get("allow_interaction"))
        prompt = f"{prompt}\n\n{interaction_instruction(bool(allow_interaction))}"

        if skill_context.strip():
            selected = "\n".join(f"- {path}" for path in skill_files) if skill_files else f"- {skill_root}"
            prompt = self._wrap_with_agent_profile(prompt, selected, agent_name)
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
    ) -> dict[str, str]:
        step_output_artifact = ""
        if step_config:
            step_output_artifact = str(step_config.get("outputFile") or step_config.get("filename") or "").strip()
        step_output = read_text(output_dir / step_output_artifact) if step_output_artifact else ""
        current_task = run.get("_current_task") or {}
        if not isinstance(current_task, dict):
            current_task = {}
        current_task_block = ""
        if current_task:
            current_task_block = "\n".join(
                [
                    f"Task ID: {current_task.get('id', '')}",
                    f"Task Title: {current_task.get('title', '')}",
                    f"Task Index: {current_task.get('index', '')}/{current_task.get('total', '')}",
                    f"Task Owner Step: {current_task.get('owner', '')}",
                    f"Task Phase: {current_task.get('phase', '')}",
                ]
            ).strip()
        return {
            "requirement": requirement,
            "architecture": architecture,
            "project_profile": profile,
            "project_index": read_text(output_dir / "project-index.md"),
            "project_overview": project_overview(project_dir),
            "spec": read_text(output_dir / "spec.md"),
            "spec_review": read_text(output_dir / "spec-review.md"),
            "todo": read_text(output_dir / "todo.md"),
            "task_manifest": read_text(output_dir / "task-manifest.md"),
            "current_task": current_task_block,
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
            "verifier_report": read_text(output_dir / "verifier-report.json"),
            "diff_context": read_text(output_dir / "diff-context.md"),
            "diff_review": read_text(output_dir / "diff-review.md"),
            "final_review": read_text(output_dir / "final-review.md"),
            "raw_spec": read_text(output_dir / "spec.md"),
            "answers": answers,
            "guidance": guidance,
            "last_error": failure_feedback,
            "failure_feedback": failure_feedback,
            "step_output": step_output,
            "security_context": read_text(output_dir / "security-context.md"),
            "security_candidates": self._read_security_candidate_artifacts(output_dir),
            "security_candidate_scores": self._read_security_candidate_score_artifacts(output_dir),
            "security_findings": read_text(output_dir / "security-findings.md"),
            "security_report_score": read_text(output_dir / "security-report-score.md"),
            "project_path": str(run.get("project_path", "")),
            "workspace_path": str(run.get("workspace", "")),
            "validation_script": str(run.get("validation_script") or ""),
            "fallback_validation_scripts": self._fallback_validation_scripts(run),
        }

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
            if step.get("key") != "run_external_validation":
                continue
            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            value = config.get("fallbackValidationScripts") or config.get("fallback_validation_scripts") or []
            if isinstance(value, str):
                items = [item.strip() for item in value.split(",") if item.strip()]
            elif isinstance(value, list):
                items = [str(item).strip() for item in value if str(item).strip()]
            else:
                items = []
            return "\n".join(f"- `{item}`" for item in items) if items else "- None configured."
        return "- None configured."

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
                "Do not call tools, do not call functions, and do not output JSON unless the task explicitly asks for JSON.\n\n"
                f"Reference files:\n{selected_skills}\n\n"
            )
        else:
            skill_header = (
                f"Reference instruction files have been loaded for the {agent_name} agent as background methodology only. "
                "Do not call external tools unless the workflow step explicitly requires it. "
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
