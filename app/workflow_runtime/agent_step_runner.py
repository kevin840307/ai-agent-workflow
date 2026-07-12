from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import UserInputRequired, WorkflowError
from app.runtime_modules.files import failure_feedback_for_step, project_content_snapshot, restore_project_content_snapshot, project_overview
from app.core.paths import read_text, write_text
from app.security.agent_project_config import ensure_agent_project_configs
from app.services.agent_execution_service import AgentExecutionService

from .agents import AgentManager, AgentRequest
from .prompt_builder import PromptBuilder
from .questions import extract_user_questions
from .context_handoff import write_context_handoff
from .agent_output_parser import json_with_triple_quoted_strings, tool_call_name, tool_call_payload

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]
AppendSessionMessageFn = Callable[[str, str, str], Awaitable[Any]]
UpdateRunFn = Callable[[str, Callable[[dict[str, Any]], Any]], Awaitable[dict[str, Any] | None]]


def validation_script_snapshot(run: dict[str, Any], project_dir: Path) -> tuple[Path, bytes] | None:
    contract = run.get("validation_contract") or {}
    raw = run.get("validation_script") or contract.get("display_path")
    if not raw:
        return None
    candidate = Path(str(raw)).expanduser()
    target = candidate if candidate.is_absolute() else project_dir / candidate
    try:
        target = target.resolve()
        target.relative_to(project_dir.resolve())
        return (target, target.read_bytes()) if target.is_file() else None
    except (OSError, ValueError):
        return None


def restore_validation_script(snapshot: tuple[Path, bytes] | None) -> bool:
    if snapshot is None:
        return False
    target, expected = snapshot
    try:
        current = target.read_bytes() if target.is_file() else None
        if current == expected:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(expected)
        return True
    except OSError:
        return False


class AgentStepRunner:
    def __init__(
        self,
        *,
        agent_manager: AgentManager,
        prompt_builder: PromptBuilder,
        bus: Any,
        log: LogFn,
        refresh_artifacts: RefreshArtifactsFn,
        append_session_message: AppendSessionMessageFn,
        update_run: UpdateRunFn | None = None,
    ) -> None:
        self.agent_manager = agent_manager
        self.prompt_builder = prompt_builder
        self.bus = bus
        self.log = log
        self.refresh_artifacts = refresh_artifacts
        self.append_session_message = append_session_message
        self.update_run = update_run
        self.execution = AgentExecutionService()
        self.session_manager = self.execution.session_manager

    async def run(
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
        output_dir = Path(run["workspace"]) / "output"
        input_dir = Path(run["workspace"]) / "input"
        step_config = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        agent = self.agent_manager.resolve(step_config.get("config") or {}, agent_name=agent_name or step_config.get("agent"))
        agent_name = agent.name
        config = step_config.get("config") or {}
        prompt_result = self.prompt_builder.build(
            run,
            step_key,
            prompt_name,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
        cwd = self._execution_project_dir(run)
        ensure_agent_project_configs(cwd)
        workspace_path = Path(run["workspace"]).expanduser().resolve()
        run["_current_step_key"] = step_key
        # Session reuse is decided centrally by role (planning/build/validation/review).
        # A requested fresh session must be fresh for every provider. Review and
        # rollback recovery cannot safely reuse build conversation state.
        fresh_once = bool(run.pop("_fresh_agent_session_once", False))
        force_fresh = bool(run.get("_force_fresh_qwen_session"))
        session_decision = self.session_manager.resolve(
            run,
            step_key=step_key,
            agent=agent_name,
            fresh=bool(fresh_session or fresh_once or force_fresh),
            reason="review_or_recovery" if (fresh_session or fresh_once or force_fresh) else None,
        )
        session_id = session_decision.session_id
        prompt_text = self._harden_prompt_for_step(
            step_key,
            self._compact_retry_prompt_if_reusing_session(
                run,
                step_key,
                prompt_result.prompt,
                prompt_file=str(workspace_path / prompt_result.relative_prompt_path),
                cwd=cwd,
                session_id=session_id,
                config=config,
            ),
        )
        effective_prompt_rel = f"prompts/{step_key}.effective.md"
        effective_prompt_path = workspace_path / effective_prompt_rel
        write_text(effective_prompt_path, prompt_text)
        prompt_meta_rel = f"prompts/{step_key}.prompt-meta.json"
        prompt_meta = {
            "step_key": step_key,
            "agent": agent_name,
            "session_id": session_id,
            "template_prompt_path": prompt_result.relative_prompt_path,
            "effective_prompt_path": effective_prompt_rel,
            "prompt_chars": len(prompt_result.prompt),
            "effective_prompt_chars": len(prompt_text),
            "compact_retry": self._is_compact_retry_prompt(prompt_text),
            "cwd": str(cwd),
        }
        write_text(workspace_path / prompt_meta_rel, json.dumps(prompt_meta, indent=2, ensure_ascii=False))
        request = AgentRequest(
            run_id=run["id"],
            step_key=step_key,
            prompt=prompt_text,
            cwd=cwd,
            session_id=session_id,
            metadata={
                "project_path": str(cwd),
                "workspace_path": str(workspace_path),
                "prompt_file": str(effective_prompt_path),
                "template_prompt_file": str(workspace_path / prompt_result.relative_prompt_path),
                "write_root": str(cwd),
                "read_policy": "unrestricted",
                "unattended": bool(run.get("unattended")),
                "agent": agent_name,
            },
        )
        display_cmd = agent.command_preview(request)
        await self.log(run, f"{step_key}: agent={agent_name}, command=`{display_cmd}`, cwd={cwd}")
        await self.log(run, f"{step_key}: prompt length={len(prompt_text)} chars, passed by file={prompt_result.relative_prompt_path}")
        if self._is_compact_retry_prompt(prompt_text):
            await self.log(run, f"{step_key}: compact retry prompt enabled because agent session is being reused")
        if prompt_result.skill_files:
            await self.log(run, f"{step_key}: selected skills: {', '.join(path.parent.name for path in prompt_result.skill_files)}")
        await self.log(run, f"{step_key}: prompt saved to {prompt_result.relative_prompt_path}")
        await self.refresh_artifacts(run["id"])
        await self._publish_status(run["id"], agent_name, step_key, self._running_status(run, step_config, agent_name, step_key, artifact))
        read_only_step = self._is_read_only_step(step_key, step_config)
        read_only_snapshot = project_content_snapshot(cwd) if read_only_step else None
        protected_validation_snapshot = validation_script_snapshot(run, cwd)

        async def publish_agent_output(stream: str, text: str) -> None:
            if not text:
                return
            if stream == "status":
                await self._publish_status(run["id"], agent_name, step_key, text)
                return
            if stream == "stdout" and not self._show_agent_stdout():
                # Agent stdout is the artifact body.  It is still captured and
                # written to output/*.md, but hiding it from the live console keeps
                # large direct-edit summaries and token streams from flooding logs.
                return
            await self.bus.publish(run["id"], {"type": "agent_output", "agent": agent_name, "step": step_key, "stream": stream, "text": text})
            # Legacy qwen_output events double every token in the modern UI, so
            # keep them opt-in only for older external dashboards.
            if agent_name == "qwen" and self._emit_legacy_qwen_output():
                await self.bus.publish(run["id"], {"type": "qwen_output", "step": step_key, "stream": stream, "text": text})

        def recovery_prompt(failure: dict[str, Any], _request: AgentRequest, _attempt: int) -> str:
            if failure.get("code") != "CONTEXT_LIMIT_REACHED":
                return prompt_text
            handoff = self._write_session_handoff(run, step_key, cwd, workspace_path, str(failure.get("message") or "context limit"))
            return handoff + "\n\n---\n\n" + prompt_text

        outcome = await self.execution.execute(
            agent,
            request,
            on_output=publish_agent_output,
            on_status=lambda message: self._publish_status(run["id"], agent_name, step_key, message),
            recovery_prompt_factory=recovery_prompt,
        )
        result = outcome.result
        recovery_reason = str((outcome.recoveries[-1] if outcome.recoveries else {}).get("code") or "").lower() or None
        if outcome.recoveries:
            for recovery in outcome.recoveries:
                await self.log(
                    run,
                    f"{step_key}: agent recovery {recovery['attempt']}/{len(outcome.recoveries)} "
                    f"code={recovery['code']} strategy={recovery['strategy']} fresh={recovery['fresh_session']}",
                )
            if outcome.request.session_id is None and request.session_id:
                self.session_manager.invalidate(run, step_key=step_key, agent=agent_name, reason=recovery_reason or "agent_recovery")
        self.session_manager.record(
            run,
            role=session_decision.role,
            agent=agent_name,
            session_id=result.session_id or outcome.request.session_id,
            recovery_reason=recovery_reason,
        )
        if self.update_run is not None:
            role_sessions_snapshot = json.loads(json.dumps(run.get("role_session_ids") or {}))
            provider_sessions_snapshot = json.loads(json.dumps(run.get("agent_session_ids") or {}))
            records_snapshot = list(run.get("session_records") or [])[-100:]
            invalidations_snapshot = list(run.get("session_invalidations") or [])[-50:]
            qwen_session_snapshot = run.get("qwen_session_id")
            def persist_session_state(item: dict[str, Any]) -> None:
                item["role_session_ids"] = role_sessions_snapshot
                item["agent_session_ids"] = provider_sessions_snapshot
                item["session_records"] = records_snapshot
                item["session_invalidations"] = invalidations_snapshot
                if qwen_session_snapshot:
                    item["qwen_session_id"] = qwen_session_snapshot
            persisted = await self.update_run(run["id"], persist_session_state)
            if persisted:
                # Session persistence may return an older serialized Run snapshot.
                # Only merge session-owned fields so freshly produced validation,
                # task, checkpoint, retry, and evidence state cannot be overwritten.
                for field in (
                    "role_session_ids",
                    "agent_session_ids",
                    "session_records",
                    "session_invalidations",
                    "qwen_session_id",
                ):
                    if field in persisted:
                        run[field] = persisted[field]
        if restore_validation_script(protected_validation_snapshot):
            counters = run.setdefault("recovery_counters", {})
            counters["deterministic_repairs"] = int(counters.get("deterministic_repairs") or 0) + 1
            run.setdefault("protected_file_repairs", []).append(
                {"step_key": step_key, "path": str(protected_validation_snapshot[0]), "reason": "VALIDATION_SCRIPT_MUTATED"}
            )
            await self.log(run, f"{step_key}: restored user validation script after agent mutation")
        if read_only_snapshot is not None:
            current_snapshot = project_content_snapshot(cwd)
            if current_snapshot != read_only_snapshot:
                restore_project_content_snapshot(cwd, read_only_snapshot)
                counters = run.setdefault("recovery_counters", {})
                counters["deterministic_repairs"] = int(counters.get("deterministic_repairs") or 0) + 1
                run.setdefault("read_only_mutations_reverted", []).append(
                    {"step_key": step_key, "agent": agent_name, "reason": "REVIEW_MUTATED_PROJECT"}
                )
                await self.log(
                    run,
                    f"{step_key}: REVIEW_MUTATED_PROJECT: project changes were reverted; "
                    "continuing with artifact validation.",
                )
        output = result.output
        if not output.strip():
            raise WorkflowError(f"{step_key}: {agent_name} returned empty stdout.")
        if "ask_user_question" in output and '"arguments"' in output:
            write_text(output_dir / artifact, output + "\n")
            questions = extract_user_questions(output)
            if allow_interaction is None:
                allow_interaction = bool(step_config.get("allow_interaction"))
            if not allow_interaction:
                raise WorkflowError(
                    f"{step_key}: {agent_name} asked for user input but this step has interaction disabled in the workflow config."
                )
            write_text(input_dir / "questions.md", questions + "\n")
            await self.append_session_message(run["session_id"], "assistant", f"{agent_name} asks:\n\n{questions}")
            await self.refresh_artifacts(run["id"])
            raise UserInputRequired(f"{step_key}: {agent_name} needs more user input. See input/questions.md.")

        raw_tool_name = self._tool_call_name(output)
        if raw_tool_name and self._reprompt_on_tool_call_json(step_key, config):
            await self.log(run, f"{step_key}: {agent_name} returned tool-call JSON `{raw_tool_name}`; sending one CLI-style correction prompt instead of failing immediately")
            correction = self._render_tool_call_json_correction_prompt(
                step_key,
                raw_tool_name,
                cwd=cwd,
                artifact=artifact,
            )
            correction_request = AgentRequest(
                run_id=run["id"],
                step_key=step_key,
                prompt=correction,
                cwd=cwd,
                session_id=session_id,
                metadata={
                    "project_path": str(cwd),
                    "workspace_path": str(workspace_path),
                    "prompt_file": str(effective_prompt_path),
                    "template_prompt_file": str(workspace_path / prompt_result.relative_prompt_path),
                    "write_root": str(cwd),
                    "read_policy": "unrestricted",
                    "tool_call_json_reprompt": raw_tool_name,
                },
            )
            correction_outcome = await self.execution.execute(
                agent,
                correction_request,
                on_output=publish_agent_output,
                on_status=lambda message: self._publish_status(run["id"], agent_name, step_key, message),
            )
            correction_result = correction_outcome.result
            output = correction_result.output
            if not output.strip():
                raise WorkflowError(f"{step_key}: {agent_name} returned empty stdout after tool-call JSON correction prompt.")

        tool_name = self._tool_call_name(output)
        if tool_name:
            write_text(output_dir / artifact, output + "\n")
            raise WorkflowError(
                f"{step_key}: {agent_name} returned tool-call JSON `{tool_name}` after the correction prompt. "
                "The workflow controller does not execute agent edit/write JSON. Use Qwen/OpenCode real file edit/write tools so the project files actually change."
            )

        if "No specification found" in output:
            raise WorkflowError(f"{step_key}: {agent_name} did not treat the prompt file as the task.")
        write_text(output_dir / artifact, output + "\n")
        await self._publish_status(run["id"], agent_name, step_key, f"Finished writing output/{artifact}.")
        await self.log(run, f"{step_key}: wrote output/{artifact}")
        await self.refresh_artifacts(run["id"])
        return output


    @staticmethod
    def _reprompt_on_tool_call_json(step_key: str, config: dict[str, Any]) -> bool:
        value = config.get("repromptOnToolCallJson")
        if value is not None:
            return str(value).lower() not in {"0", "false", "no", "off"}
        return step_key in {"build", "generate_tests", "auto_generation"}

    @staticmethod
    def _render_tool_call_json_correction_prompt(step_key: str, tool_name: str, *, cwd: Path, artifact: str) -> str:
        return "\n".join(
            [
                "# Continue this CLI task",
                "",
                f"Step: {step_key}",
                f"Project Path: {cwd}",
                f"Previous response problem: you returned tool-call JSON `{tool_name}` instead of performing real project edits.",
                "",
                "Do this now:",
                "- Continue the same task from the previous prompt.",
                "- Use the CLI agent's actual file edit/write capability to modify files inside Project Path.",
                "- Do not return JSON for edit_file/write_file/open_code/use_exit_plan_mode.",
                "- Do not output FILE/CONTENT/END_FILE blocks as a substitute for editing files.",
                "- Keep writes inside Project Path only.",
                f"- After the real edits are done, return a short Markdown summary for output/{artifact}.",
            ]
        )


    @staticmethod
    def _running_status(run: dict[str, Any], step_record: dict[str, Any], agent_name: str, step_key: str, artifact: str) -> str:
        current_task = run.get("_current_task") or {}
        task_bits: list[str] = []
        if current_task:
            task_id = str(current_task.get("id") or "").strip()
            title = str(current_task.get("title") or "").strip()
            index = current_task.get("index")
            total = current_task.get("total")
            if task_id:
                task_bits.append(task_id)
            if index and total:
                task_bits.append(f"{index}/{total}")
            if title:
                task_bits.append(title)
            task_text = " · ".join(task_bits)
            return f"Working on {task_text}. The agent is producing output/{artifact}."

        name = str(step_record.get("name") or step_key).strip()
        description = str(step_record.get("description") or "").strip()
        outputs = step_record.get("outputs") or step_record.get("expectedFiles") or []
        if isinstance(outputs, str):
            output_text = outputs
        elif isinstance(outputs, list) and outputs:
            output_text = ", ".join(str(item) for item in outputs[:3])
            if len(outputs) > 3:
                output_text += f", +{len(outputs) - 3} more"
        else:
            output_text = artifact
        parts = [f"{name}: {description}" if description else f"{name} is running", f"Target output: {output_text}"]
        return ". ".join(part.rstrip(".") for part in parts if part) + "."

    @staticmethod
    def _show_agent_stdout() -> bool:
        return os.environ.get("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", "0").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _emit_legacy_qwen_output() -> bool:
        return os.environ.get("QWEN_WORKFLOW_EMIT_LEGACY_QWEN_OUTPUT", "0").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_compact_retry_prompt(prompt: str) -> bool:
        return prompt.lstrip().startswith("# Compact Reuse Retry")

    @staticmethod
    def _tool_call_name(output: str) -> str:
        return tool_call_name(output)

    @staticmethod
    def _tool_call_payload(output: str) -> Any:
        return tool_call_payload(output)

    @staticmethod
    def _json_with_triple_quoted_strings(text: str) -> str:
        return json_with_triple_quoted_strings(text)

    def _compact_retry_prompt_if_reusing_session(
        self,
        run: dict[str, Any],
        step_key: str,
        full_prompt: str,
        *,
        prompt_file: str,
        cwd: Path,
        session_id: str | None,
        config: dict[str, Any],
    ) -> str:
        if not session_id:
            return full_prompt
        if not self._compact_retry_enabled(step_key, config):
            return full_prompt
        feedback = failure_feedback_for_step(
            read_text(Path(run["workspace"]) / "input" / "failure-feedback.md"),
            step_key,
            latest_only=True,
        ).strip()
        if not feedback:
            return full_prompt
        return self._render_compact_retry_prompt(
            run,
            step_key,
            feedback,
            prompt_file=prompt_file,
            cwd=cwd,
        )

    @staticmethod
    def _compact_retry_enabled(step_key: str, config: dict[str, Any]) -> bool:
        if config.get("compactRetryPromptWhenReusingSession") is not None:
            return str(config.get("compactRetryPromptWhenReusingSession")).lower() not in {"0", "false", "no", "off"}
        return step_key in {"build", "generate_tests", "auto_generation"}

    def _render_compact_retry_prompt(
        self,
        run: dict[str, Any],
        step_key: str,
        feedback: str,
        *,
        prompt_file: str,
        cwd: Path,
    ) -> str:
        current_task = run.get("_current_task") or {}
        task_lines: list[str] = []
        if isinstance(current_task, dict) and current_task:
            for label, key in [
                ("Task ID", "id"),
                ("Task title", "title"),
                ("Task index", "index"),
                ("Task total", "total"),
                ("Task phase", "phase"),
            ]:
                value = current_task.get(key)
                if value:
                    task_lines.append(f"- {label}: {value}")
        extra: list[str] = []
        if step_key == "generate_tests":
            extra.append("Import production code only from real project files listed in the previous full prompt/import map; do not invent package names from the folder title.")
            extra.append("If a callable mutates input and returns None, assert the mutated input; otherwise assert the returned value.")
        elif step_key in {"build", "auto_generation"}:
            extra.append("Fix production/project files directly inside Project Path. Do not edit tests unless this is Adaptive Auto Workflow and tests are part of the same task.")
            extra.append("Preserve already completed task outputs and existing architecture.")

        return "\n".join(
            [
                "# Compact Reuse Retry",
                "",
                "Continue the same agent session. The full workflow/task prompt was already sent earlier in this session; do not restart from scratch or invent a new architecture.",
                "",
                f"Step: {step_key}",
                f"Project Path: {cwd}",
                f"Original full prompt file for reference: {prompt_file}",
                "",
                "Current task:",
                *(task_lines or ["- No task-scoped metadata."]),
                "",
                "Concrete failure feedback to fix now:",
                feedback[-8000:],
                "",
                "Repair instructions:",
                "- Use the previous full prompt, current project files, and this failure feedback as the source of truth.",
                "- Make the smallest project changes needed for this retry.",
                "- Keep writes inside Project Path only.",
                "- Do not output tool-call JSON or call tools such as use_exit_plan_mode; this workflow expects artifact text plus real direct project edits.",
                "- If the previous failure says tool-call JSON, edit_file, write_file, open_code, enter_plan_mode, exit_plan_mode, or empty output, stop using tool-call JSON entirely and use the CLI's real file edit/write capability instead.",
                "- Do not rely on platform FILE/CONTENT/END_FILE fallback in real Qwen/OpenCode runs; production workflow completion is verified from actual project file diffs.",
                *[f"- {item}" for item in extra],
                "",
                "Return only the artifact/direct-edit result expected by this step.",
            ]
        ).strip()

    @staticmethod
    def _harden_prompt_for_step(step_key: str, prompt: str) -> str:
        base_guard = """

Workspace safety guard:
- Current working directory is the selected Project Path.
- You may read files anywhere when needed for context.
- You must only create, modify, delete, or rename files inside the selected Project Path.
- Do not write absolute paths, parent-directory paths, `.git`, `.qwen`, `opencode.json`, `.ai-workflow`, or `.qwen-workflow`.
- Do not run dangerous commands, `git commit`, `git push`, installs, deletes, or any command that changes repository history, remote state, or files outside the project.
- Use CLI file edit/write tools only when they actually modify files in this non-interactive run.
- If tool use would be returned as JSON such as `{"name": "edit_file"}`, do not emit that JSON; use the CLI's real file edit/write capability or report the concrete blocker in the artifact.
- Real Qwen/OpenCode runs must not depend on platform FILE/CONTENT/END_FILE materialization. The platform verifies actual project file diffs.
"""
        if step_key in {"plan_tasks", "generate_task_prompts", "implementation_review", "ai_review", "final_review", "diff_review"}:
            step_guard = """

Read-only planning/review guard:
- Do not create, edit, delete, or rename any project file.
- Inspect the current project and return only the requested structured artifact/JSON response.
- The controller will reject and revert any project mutation from this step.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "build":
            step_guard = """

Build output guard:
- You are in the Build step. Create or modify production project files directly with the CLI agent's real file edit/write capability.
- Do not create, modify, copy, or include test files or test-file content.
- Do not write paths under tests/ and do not write files named test_*.py.
- Do not return edit tool JSON. Do not rely on platform FILE/CONTENT/END_FILE materialization in real runs.
- The project must contain at least one non-test production file that implements the current Requirement.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "auto_generation":
            step_guard = """

Adaptive generation output guard:
- You are in the Auto Generation Workflow step.
- Materialize the requested project change through real direct edits inside Project Path.
- Do not return edit tool JSON. Do not rely on platform FILE/CONTENT/END_FILE materialization in real runs.
- You may include production files, tests, and small project documentation when useful.
- Existing validation scripts are read-only unless the user explicitly asked to modify them.
- The project must contain at least one changed file for this task.
- Do not create workflow artifacts such as auto_generation*.md, task-output.md, run logs, or workspace notes as the task result; create the actual user-requested product/source/config/test files.
- For programming tasks, prose documentation alone is not an implementation. Create or update runnable source files for the requested language and behavior.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "generate_tests":
            step_guard = """

Generate Tests output guard:
- You are in the Generate Tests step. Create or modify test files directly with the CLI agent's real file edit/write capability.
- For Python projects, write only tests/test_*.py or tests/conftest.py.
- Do not modify production files in this step.
- Do not return edit tool JSON. Do not rely on platform FILE/CONTENT/END_FILE materialization in real runs.
"""
            return prompt.rstrip() + base_guard + step_guard
        return prompt.rstrip() + base_guard

    @staticmethod
    def _is_read_only_step(step_key: str, step_record: dict[str, Any]) -> bool:
        step_type = str(step_record.get("type") or (step_record.get("config") or {}).get("type") or "").lower()
        return step_type == "review" or step_key in {
            "plan_tasks",
            "generate_task_prompts",
            "implementation_review",
            "ai_review",
            "final_review",
            "diff_review",
        }

    @staticmethod
    def _execution_project_dir(run: dict[str, Any]) -> Path:
        patch_mode = str(run.get("patch_mode") or "auto_apply").lower().replace("-", "_")
        project = Path(run.get("project_path") or run["workspace"]).expanduser().resolve()
        original_value = run.get("original_project_path")
        original = Path(original_value).expanduser().resolve() if original_value else project
        # auto_apply always executes in the exact user-selected project. This
        # prevents C:\...\sort2 from silently becoming a run-local
        # .ai-workflow/.../isolated-workspace directory.
        if patch_mode == "auto_apply":
            project = original
            workflow_root = original / ".ai-workflow"
            try:
                project.relative_to(workflow_root)
            except ValueError:
                pass
            else:
                raise WorkflowError("auto_apply Project Path cannot be inside .ai-workflow")
        project.mkdir(parents=True, exist_ok=True)
        return project

    def _session_id_for_agent(self, run: dict[str, Any], agent_name: str) -> str | None:
        step_key = str(run.get("_current_step_key") or "")
        return self.session_manager.resolve(run, step_key=step_key, agent=agent_name).session_id

    @staticmethod
    def _session_role(step_key: str) -> str:
        return AgentSessionManager.role_for_step(step_key)

    def _write_session_handoff(self, run: dict[str, Any], step_key: str, cwd: Path, workspace_path: Path, error: str) -> str:
        _payload, markdown = write_context_handoff(
            run,
            step_key=step_key,
            project_dir=cwd,
            workspace_path=workspace_path,
            error=error,
        )
        return markdown

    async def _publish_status(self, run_id: str, agent_name: str, step_key: str, message: str) -> None:
        await self.bus.publish(run_id, {"type": "agent_status", "agent": agent_name, "step": step_key, "message": message})
        if agent_name == "qwen":
            await self.bus.publish(run_id, {"type": "qwen_status", "step": step_key, "message": message})
