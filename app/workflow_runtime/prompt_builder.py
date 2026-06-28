from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.runtime_errors import WorkflowError
from app.runtime_files import failure_feedback_for_step, project_overview
from app.runtime_paths import DEFAULT_SKILL_PATH, ROOT, SYSTEM_WORKFLOW_ID, WORKFLOW_BUNDLES_DIR, read_text, write_text
from app.runtime_skills import load_skill_context

from .questions import interaction_instruction


def workflow_prompt_path(name: str, run: dict[str, Any] | None = None) -> Path:
    workflow_folder = (run or {}).get("workflow_folder") or (run or {}).get("workflow_id") or SYSTEM_WORKFLOW_ID
    normalized = name.replace("\\", "/").lstrip("/")
    if normalized.startswith("prompts/"):
        return WORKFLOW_BUNDLES_DIR / workflow_folder / normalized
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
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        answers = read_text(input_dir / "answers.md")
        guidance = read_text(input_dir / "guidance.md")
        failure_feedback = failure_feedback_for_step(read_text(input_dir / "failure-feedback.md"), step_key)
        project_dir = Path(run.get("project_path") or ROOT)
        architecture = read_text(project_dir / "architecture.md")
        skill_context, skill_files = load_skill_context(str(DEFAULT_SKILL_PATH), step_key, requirement)
        prompt_template = read_text(workflow_prompt_path(prompt_name, run))
        prompt = load_prompt(
            prompt_name,
            run=run,
            requirement=requirement,
            architecture=architecture,
            project_overview=project_overview(project_dir),
            spec=read_text(output_dir / "spec.md"),
            todo=read_text(output_dir / "todo.md"),
            test_plan=read_text(output_dir / "test-plan.md"),
            test_result=read_text(output_dir / "test-result.md"),
            raw_spec=read_text(output_dir / "spec.md"),
            answers=answers,
            guidance=guidance,
            last_error=failure_feedback,
            failure_feedback=failure_feedback,
            project_path=run.get("project_path", ""),
            workspace_path=run.get("workspace", ""),
        )
        if answers.strip() and "{{answers}}" not in prompt_template:
            prompt = f"{prompt}\n\nUser replies from previous workflow interaction:\n\n{answers.strip()}\n"
        if guidance.strip() and "{{guidance}}" not in prompt_template:
            prompt = f"{prompt}\n\nUser step guidance added during the workflow:\n\n{guidance.strip()}\n"
        if failure_feedback.strip() and "{{last_error}}" not in prompt_template and "{{failure_feedback}}" not in prompt_template:
            prompt = (
                f"{prompt}\n\n"
                "Failure feedback from previous retry attempts. Fix these concrete errors before producing this step output:\n\n"
                f"{failure_feedback.strip()}\n"
            )
        if architecture.strip() and step_key != "prepare_project" and "{{architecture}}" not in prompt_template:
            prompt = f"{prompt}\n\nCurrent project architecture context from architecture.md:\n\n{architecture.strip()}\n"
        if allow_interaction is None:
            step_config = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
            allow_interaction = bool(step_config.get("allow_interaction"))
        prompt = f"{prompt}\n\n{interaction_instruction(bool(allow_interaction))}"

        if skill_context.strip():
            selected = "\n".join(f"- {path}" for path in skill_files) if skill_files else f"- {DEFAULT_SKILL_PATH}"
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

    def _wrap_with_agent_profile(self, prompt: str, selected_skills: str, agent_name: str) -> str:
        if agent_name == "qwen":
            skill_header = (
                "Loaded these Qwen skill files as background methodology only. "
                "Do not call tools. Output JSON only when asking the user with ask_user_question.\n\n"
                f"Selected skills:\n{selected_skills}\n\n"
            )
        else:
            skill_header = (
                f"Loaded these skill files for the {agent_name} agent as background methodology only. "
                "Do not call external tools unless the workflow step explicitly requires it. "
                "Output JSON only when asking the user with ask_user_question.\n\n"
                f"Selected skills:\n{selected_skills}\n\n"
            )
        return (
            f"{skill_header}"
            "Task follows. Output only the final artifact content requested by the task.\n\n"
            f"{prompt}\n\n"
            "Final reminder: output artifact content only, unless you need user input. "
            "Ask the user only under the strict Human interaction rule above; otherwise make reasonable assumptions and continue."
        )
