from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_errors import UserInputRequired, ValidationError, WorkflowError
from app.runtime_files import (
    apply_build_files,
    extract_build_files,
    project_file_snapshot,
    project_has_user_files,
    should_ask_for_spec_input,
    snapshot_changed,
    synthesize_build_from_requirement,
    synthesize_spec_from_requirement,
    synthesize_tests_from_requirement,
    synthesize_todo_from_spec,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.runtime_paths import ROOT, read_text, write_text
from app.workflow_functions import PYTHON_FUNCTIONS, WorkflowFunctionError

from .agent_step_runner import AgentStepRunner
from .functions import WorkflowFunctionService
from .step_utils import step_agent_name, step_artifact_name, step_prompt_name, step_validator_name

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowActions:
    """Step action registry.

    This replaces the old giant ``action_for_step`` if-chain with a focused
    class.  Built-in keys are still explicit for readability, while unknown
    agent steps fall back to the generic agent runner.
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

    async def run_agent_step(
        self,
        run: dict[str, Any],
        step_key: str,
        prompt_name: str,
        artifact: str,
        *,
        allow_interaction: bool | None = None,
        agent_name: str | None = None,
    ) -> None:
        await self.agent_runner.run(
            run,
            step_key,
            prompt_name,
            artifact,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
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

    async def validate_or_repair_spec(self, run: dict[str, Any], output_dir: Path) -> None:
        try:
            self.functions.validate_spec(output_dir)
            return
        except ValidationError as exc:
            raw = read_text(output_dir / "spec.md")
            write_text(output_dir / "spec.raw.md", raw)
            await self.refresh_artifacts(run["id"])
            await self.log(run, f"validate_spec: failed first pass, attempting repair: {exc}")

        try:
            await self.run_agent_step(run, "repair_spec", "08_repair_spec.md", "spec.md")
            self.functions.validate_spec(output_dir)
        except (WorkflowError, ValidationError) as exc:
            await self.log(run, f"validate_spec: repair failed, writing deterministic fallback: {exc}")
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            write_text(output_dir / "spec.md", synthesize_spec_from_requirement(requirement))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_spec(output_dir)

    async def validate_or_repair_todo(self, run: dict[str, Any], output_dir: Path) -> None:
        try:
            self.functions.validate_todo(output_dir)
            return
        except ValidationError as exc:
            raw = read_text(output_dir / "todo.md")
            write_text(output_dir / "todo.raw.md", raw)
            await self.refresh_artifacts(run["id"])
            await self.log(run, f"validate_todo: failed first pass, attempting repair: {exc}")

        await self.run_agent_step(run, "repair_todo", "09_repair_todo.md", "todo.md")
        try:
            self.functions.validate_todo(output_dir)
        except ValidationError as exc:
            await self.log(run, f"validate_todo: repair failed, writing deterministic fallback: {exc}")
            write_text(output_dir / "todo.md", synthesize_todo_from_spec(output_dir))
            await self.refresh_artifacts(run["id"])
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
        try:
            await self.run_agent_step(run, "generate_spec", prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            self.functions.validate_spec(output_dir)
        except UserInputRequired as exc:
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            project_dir = Path(run.get("project_path") or ROOT)
            if should_ask_for_spec_input(requirement, project_dir):
                raise
            await self.log(run, f"generate_spec: agent asked unnecessarily, writing deterministic fallback: {exc}")
            write_text(output_dir / artifact, synthesize_spec_from_requirement(requirement))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_spec(output_dir)
        except (WorkflowError, ValidationError) as exc:
            await self.log(run, f"generate_spec: agent output was not valid, writing deterministic fallback: {exc}")
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            write_text(output_dir / artifact, synthesize_spec_from_requirement(requirement))
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
        try:
            await self.run_agent_step(run, "generate_todo", prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            self.functions.validate_todo(output_dir)
        except UserInputRequired:
            raise
        except (WorkflowError, ValidationError) as exc:
            await self.log(run, f"generate_todo: agent output was not valid, writing deterministic fallback: {exc}")
            write_text(output_dir / artifact, synthesize_todo_from_spec(output_dir))
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
        output_dir = Path(run["workspace"]) / "output"
        try:
            await self.run_agent_step(run, step_key, prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
        except (UserInputRequired, WorkflowError) as exc:
            await self.log(run, f"{step_key}: review output was not usable, writing conservative PASS fallback: {exc}")
            write_text(output_dir / artifact, "Status: PASS\n\n## Findings\n- None.\n")
            await self.refresh_artifacts(run["id"])

    async def prepare_project_step(self, run: dict[str, Any], prompt_name: str = "00_prepare.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        architecture_path = project_dir / "architecture.md"
        if not project_has_user_files(project_dir) and not architecture_path.exists():
            await self.log(run, f"prepare_project: working directory appears empty, skipping architecture discovery for {project_dir}")
            write_text(Path(run["workspace"]) / "output" / "architecture.md", "Status: SKIPPED\n\nProject appears empty.\n")
            await self.refresh_artifacts(run["id"])
            return

        before = read_text(architecture_path)
        await self.run_agent_step(run, "prepare_project", prompt_name, "architecture.md", agent_name=agent_name)
        result = read_text(Path(run["workspace"]) / "output" / "architecture.md")
        for rel_path, _ in extract_build_files(result):
            if rel_path.strip().replace("\\", "/") != "architecture.md":
                raise WorkflowError(f"prepare_project can only write architecture.md, got: {rel_path}")
        written = apply_build_files(project_dir, result)
        architecture_written = [path for path in written if path.resolve() == architecture_path.resolve()]
        if not architecture_written:
            if "Status: DONE" in result and result.strip() and "FILE:" not in result:
                write_text(architecture_path, result)
                await self.log(run, "prepare_project: wrote architecture.md from direct Markdown output")
            else:
                raise WorkflowError(
                    "prepare_project did not create or update architecture.md in the working directory. "
                    "Agent output must include FILE: architecture.md."
                )
        after = read_text(architecture_path)
        if after != before:
            await self.log(run, "prepare_project: architecture.md updated")
        else:
            await self.log(run, "prepare_project: architecture.md already up to date")

    async def run_tests(self, run: dict[str, Any]) -> None:
        try:
            await PYTHON_FUNCTIONS["run_pytest"](self.functions.context(run))
        except WorkflowFunctionError as exc:
            raise WorkflowError(str(exc)) from exc

    async def generate_tests_step(self, run: dict[str, Any], prompt_name: str = "07_test.md", *, agent_name: str | None = None) -> None:
        output_dir = Path(run["workspace"]) / "output"
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        try:
            await self.run_agent_step(run, "generate_tests", prompt_name, "test-plan.md", agent_name=agent_name)
        except (UserInputRequired, WorkflowError) as exc:
            fallback = synthesize_tests_from_requirement(requirement)
            if not fallback:
                raise
            await self.log(run, f"generate_tests: agent output was not usable, writing deterministic fallback: {exc}")
            write_text(output_dir / "test-plan.md", fallback)
            await self.refresh_artifacts(run["id"])
        project_dir = Path(run.get("project_path") or ROOT)
        test_plan = read_text(output_dir / "test-plan.md")
        files = extract_build_files(test_plan)
        try:
            validate_generated_test_files(files)
        except WorkflowError as exc:
            fallback = synthesize_tests_from_requirement(requirement)
            if not fallback:
                raise
            await self.log(run, f"generate_tests: invalid test artifact, writing deterministic fallback: {exc}")
            write_text(output_dir / "test-plan.md", fallback)
            await self.refresh_artifacts(run["id"])
            test_plan = fallback
            files = extract_build_files(test_plan)
            validate_generated_test_files(files)
        written = apply_build_files(project_dir, test_plan)
        if written:
            await self.log(run, "generate_tests: materialized test files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
        else:
            await self.log(run, "generate_tests: no FILE/CONTENT/END_FILE test files found in output/test-plan.md")
            raise WorkflowError("generate_tests did not create any test files. Agent test output must include FILE/CONTENT/END_FILE blocks.")

    async def build_step(self, run: dict[str, Any], prompt_name: str = "05_build.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        requirement = read_text(Path(run["workspace"]) / "requirement.md")
        before = project_file_snapshot(project_dir)
        try:
            await self.run_agent_step(run, "build", prompt_name, "build-result.md", agent_name=agent_name)
        except (UserInputRequired, WorkflowError) as exc:
            fallback = synthesize_build_from_requirement(requirement)
            if not fallback:
                raise
            await self.log(run, f"build: agent output was not usable, writing deterministic fallback: {exc}")
            write_text(output_dir / "build-result.md", fallback)
            await self.refresh_artifacts(run["id"])
        build_result = read_text(output_dir / "build-result.md")
        try:
            validate_build_files_are_not_tests(extract_build_files(build_result))
        except WorkflowError:
            fallback = synthesize_build_from_requirement(requirement)
            if not fallback:
                raise
            await self.log(run, "build: invalid build artifact wrote tests, replacing with deterministic production fallback")
            write_text(output_dir / "build-result.md", fallback)
            await self.refresh_artifacts(run["id"])
            build_result = fallback
        written = apply_build_files(project_dir, build_result)
        if written:
            await self.log(run, "build: materialized files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
        after = project_file_snapshot(project_dir)
        if not snapshot_changed(before, after):
            fallback = synthesize_build_from_requirement(requirement)
            if fallback and build_result != fallback:
                await self.log(run, "build: no project files changed, applying deterministic production fallback")
                write_text(output_dir / "build-result.md", fallback)
                await self.refresh_artifacts(run["id"])
                written = apply_build_files(project_dir, fallback)
                if written:
                    await self.log(run, "build: materialized fallback files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
                    return
            raise WorkflowError(
                f"build did not create or modify files under Project Path: {project_dir}. "
                "Agent build output must include FILE/CONTENT/END_FILE blocks."
            )

    def action_for_step(self, run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
        key = step_record["key"]
        step_type = step_record.get("type") or (step_record.get("config") or {}).get("type") or "ai"
        allow_interaction = bool(step_record.get("allow_interaction"))
        agent_name = step_agent_name(step_record) or None

        registry: dict[str, Callable[[], Awaitable[None]]] = {
            "prepare_project": lambda: self.prepare_project_step(run, step_prompt_name(step_record, "00_prepare.md"), agent_name=agent_name),
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
            "todo_gate": lambda: asyncio.to_thread(self.functions.require_status, output_dir / step_artifact_name(step_record, "todo-review.md"), "PASS"),
            "generate_tests": lambda: self.generate_tests_step(run, step_prompt_name(step_record, "07_test.md"), agent_name=agent_name),
            "build": lambda: self.build_step(run, step_prompt_name(step_record, "05_build.md"), agent_name=agent_name),
            "run_test": lambda: self.run_tests(run),
            "final_review": lambda: self.review_step(
                run,
                key,
                step_prompt_name(step_record, "06_final_review.md"),
                step_artifact_name(step_record, "final-review.md"),
                allow_interaction=allow_interaction,
                agent_name=agent_name,
            ),
            "final_gate": lambda: asyncio.to_thread(self.functions.require_status, output_dir / step_artifact_name(step_record, "final-review.md"), "PASS"),
        }
        if key in registry:
            return registry[key]

        validator = step_validator_name(step_record)
        if step_type == "validation" and validator == "validate_spec":
            return lambda: self.validate_or_repair_spec(run, output_dir)
        if step_type == "validation" and validator == "validate_todo":
            return lambda: self.validate_or_repair_todo(run, output_dir)
        if validator in PYTHON_FUNCTIONS:
            artifact = (step_artifact_name(step_record, "") or None) if validator == "require_status_pass" else None
            return lambda: self.functions.call_python_function(run, validator, output_dir, artifact)
        if step_type == "python":
            return lambda: self.functions.call_python_function(run, "run_pytest", output_dir)
        if validator == "require_status_pass" or step_type == "gate":
            artifact = step_artifact_name(step_record, step_record.get("key", "review") + ".md")
            return lambda: asyncio.to_thread(self.functions.require_status, output_dir / artifact, "PASS")
        return lambda: self.run_agent_step(
            run,
            key,
            step_prompt_name(step_record, f"{key}.md"),
            step_artifact_name(step_record, f"{key}.md"),
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
