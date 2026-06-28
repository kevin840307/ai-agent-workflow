from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_errors import UserInputRequired, ValidationError, WorkflowError
from app.runtime_files import (
    apply_build_files,
    apply_extracted_files,
    extract_build_files,
    project_file_snapshot,
    project_has_user_files,
    should_ask_for_spec_input,
    snapshot_changed,
    split_build_files,
    synthesize_spec_from_requirement,
    synthesize_todo_from_spec,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.runtime_paths import ROOT, read_text, write_text
from app.workflow_functions import PYTHON_FUNCTIONS, WorkflowFunctionError

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
    step_validator_name,
)

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowActions:
    """Step action registry driven by workflow.json.

    Built-in step keys keep their specialized safety behavior, but prompt path,
    artifact name, agent/provider, review strategy, retry, timeout, and validator
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
        try:
            await self.run_agent_step(run, "generate_spec", prompt_name, artifact, allow_interaction=allow_interaction, agent_name=agent_name)
            self.functions.validate_spec(output_dir)
        except UserInputRequired as exc:
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            project_dir = Path(run.get("project_path") or ROOT)
            if should_ask_for_spec_input(requirement, project_dir):
                raise
            await self.log(run, f"generate_spec: agent asked unnecessarily, writing deterministic fallback: {exc}")
            write_text(output_dir / normalize_artifact_name(artifact), synthesize_spec_from_requirement(requirement))
            await self.refresh_artifacts(run["id"])
            self.functions.validate_spec(output_dir)
        except (WorkflowError, ValidationError) as exc:
            await self.log(run, f"generate_spec: agent output was not valid, writing deterministic fallback: {exc}")
            requirement = read_text(Path(run["workspace"]) / "requirement.md")
            write_text(output_dir / normalize_artifact_name(artifact), synthesize_spec_from_requirement(requirement))
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
            write_text(output_dir / normalize_artifact_name(artifact), synthesize_todo_from_spec(output_dir))
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
        if not project_has_user_files(project_dir) and not architecture_path.exists():
            await self.log(run, f"prepare_project: working directory appears empty, skipping architecture discovery for {project_dir}")
            write_text(Path(run["workspace"]) / "output" / artifact, "Status: SKIPPED\n\nProject appears empty.\n")
            await self.refresh_artifacts(run["id"])
            return

        before = read_text(architecture_path)
        await self.run_agent_step(run, "prepare_project", prompt_name, artifact, agent_name=agent_name)
        result = read_text(Path(run["workspace"]) / "output" / artifact)
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

    async def generate_tests_step(self, run: dict[str, Any], prompt_name: str = "07_test.md", artifact: str = "test-plan.md", *, agent_name: str | None = None) -> None:
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        try:
            await self.run_agent_step(run, "generate_tests", prompt_name, artifact, agent_name=agent_name)
        except UserInputRequired:
            raise
        test_plan = read_text(output_dir / artifact)
        files = extract_build_files(test_plan)
        validate_generated_test_files(files)
        project_dir = Path(run.get("project_path") or ROOT)
        written = apply_build_files(project_dir, test_plan)
        if written:
            await self.log(run, "generate_tests: materialized test files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
        else:
            await self.log(run, f"generate_tests: no FILE/CONTENT/END_FILE test files found in output/{artifact}")
            raise WorkflowError("generate_tests did not create any test files. Agent test output must include FILE/CONTENT/END_FILE blocks.")

    async def build_step(self, run: dict[str, Any], prompt_name: str = "05_build.md", artifact: str = "build-result.md", *, agent_name: str | None = None) -> None:
        project_dir = Path(run.get("project_path") or ROOT)
        output_dir = Path(run["workspace"]) / "output"
        artifact = normalize_artifact_name(artifact)
        before = project_file_snapshot(project_dir)
        try:
            await self.run_agent_step(run, "build", prompt_name, artifact, agent_name=agent_name)
        except UserInputRequired:
            raise
        build_result = read_text(output_dir / artifact)
        build_files = extract_build_files(build_result)
        production_files, ignored_test_files = split_build_files(build_files)
        if ignored_test_files:
            ignored = ", ".join(rel_path for rel_path, _ in ignored_test_files)
            if production_files:
                await self.log(run, f"build: ignored test file block(s) owned by generate_tests: {ignored}")
            else:
                raise WorkflowError(
                    "build output only contained test file blocks. Build must output production files only. "
                    f"Invalid build file(s): {ignored}"
                )
        validate_build_files_are_not_tests(production_files)
        written = apply_extracted_files(project_dir, production_files, output_label="build output")
        if written:
            await self.log(run, "build: materialized files: " + ", ".join(str(path.relative_to(project_dir)) for path in written))
        after = project_file_snapshot(project_dir)
        if not snapshot_changed(before, after):
            raise WorkflowError(
                f"build did not create or modify production files under Project Path: {project_dir}. "
                "Agent build output must include non-test FILE/CONTENT/END_FILE blocks."
            )

    def action_for_step(self, run: dict[str, Any], step_record: dict[str, Any], output_dir: Path):
        key = step_record["key"]
        config = step_config(step_record)
        step_type = step_record.get("type") or config.get("type") or "ai"
        allow_interaction = bool(step_record.get("allow_interaction"))
        agent_name = step_agent_name(step_record) or None

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
            "run_test": lambda: self.functions.call_python_function(run, step_validator_name(step_record) or "run_pytest", output_dir),
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
            artifact_validators = {"require_status_pass", "validate_security_candidates", "validate_security_report"}
            artifact = (step_artifact_name(step_record, "") or None) if validator in artifact_validators else None
            return lambda: self.functions.call_python_function(run, validator, output_dir, artifact)
        if step_type == "python":
            function_id = validator or "run_pytest"
            artifact_validators = {"validate_security_candidates", "validate_security_report"}
            artifact = (step_artifact_name(step_record, "") or None) if function_id in artifact_validators else None
            return lambda: self.functions.call_python_function(run, function_id, output_dir, artifact)
        if validator == "require_status_pass" or step_type in {"gate", "manual"}:
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
