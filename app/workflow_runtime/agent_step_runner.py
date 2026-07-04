from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import UserInputRequired, WorkflowError
from app.core.paths import read_text, write_text
from app.security.agent_project_config import ensure_agent_project_configs

from .agents import AgentManager, AgentRequest
from .error_codes import is_recoverable_session_error
from .prompt_builder import PromptBuilder
from .questions import extract_user_questions

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]
AppendSessionMessageFn = Callable[[str, str, str], Awaitable[Any]]


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
    ) -> None:
        self.agent_manager = agent_manager
        self.prompt_builder = prompt_builder
        self.bus = bus
        self.log = log
        self.refresh_artifacts = refresh_artifacts
        self.append_session_message = append_session_message

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
        prompt_text = self._harden_prompt_for_step(step_key, prompt_result.prompt)
        cwd = Path(run.get("project_path") or run["workspace"]).expanduser().resolve()
        ensure_agent_project_configs(cwd)
        workspace_path = Path(run["workspace"]).expanduser().resolve()
        base_session_id = self._session_id_for_agent(run, agent_name)
        # Qwen serve normally keeps one Qwen session per project/app session.
        # Some workflows, such as multi-agent security consensus, intentionally
        # need independent Qwen sessions for the same project.  Those steps must
        # explicitly set forceFreshQwenSession=true and keepSameSession=false.
        force_fresh_qwen = bool(
            config.get("forceFreshQwenSession")
            or config.get("isolatedQwenSession")
            or config.get("freshSessionPerAgent")
            or run.get("_force_fresh_qwen_session")
        )
        if agent_name == "qwen":
            session_id = None if fresh_session and force_fresh_qwen else base_session_id
        else:
            session_id = None if fresh_session else base_session_id
        request = AgentRequest(
            run_id=run["id"],
            step_key=step_key,
            prompt=prompt_text,
            cwd=cwd,
            session_id=session_id,
            metadata={
                "project_path": str(cwd),
                "workspace_path": str(workspace_path),
                "prompt_file": str(workspace_path / prompt_result.relative_prompt_path),
                "write_root": str(cwd),
                "read_policy": "unrestricted",
            },
        )
        display_cmd = agent.command_preview(request)
        await self.log(run, f"{step_key}: agent={agent_name}, command=`{display_cmd}`, cwd={cwd}")
        await self.log(run, f"{step_key}: prompt length={len(prompt_text)} chars, passed by file={prompt_result.relative_prompt_path}")
        if prompt_result.skill_files:
            await self.log(run, f"{step_key}: selected skills: {', '.join(path.parent.name for path in prompt_result.skill_files)}")
        await self.log(run, f"{step_key}: prompt saved to {prompt_result.relative_prompt_path}")
        await self.refresh_artifacts(run["id"])
        await self._publish_status(run["id"], agent_name, step_key, self._running_status(run, step_config, agent_name, step_key, artifact))

        async def publish_agent_output(stream: str, text: str) -> None:
            if not text:
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

        try:
            result = await agent.run_stream(request, on_output=publish_agent_output)
        except WorkflowError as exc:
            if not request.session_id or not is_recoverable_session_error(exc):
                raise
            await self.log(run, f"{step_key}: {agent_name} session failed; retrying once with a fresh session: {exc}")
            await self._publish_status(run["id"], agent_name, step_key, f"{agent_name} session recovered; retrying...")
            fresh_request = AgentRequest(
                run_id=run["id"],
                step_key=step_key,
                prompt=prompt_text,
                cwd=cwd,
                session_id=None,
                metadata={
                    "recovered_from_session_id": request.session_id,
                    "project_path": str(cwd),
                    "workspace_path": str(workspace_path),
                    "prompt_file": str(workspace_path / prompt_result.relative_prompt_path),
                    "write_root": str(cwd),
                    "read_policy": "unrestricted",
                },
            )
            result = await agent.run_stream(fresh_request, on_output=publish_agent_output)
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
        if '"name"' in output and '"arguments"' in output:
            raise WorkflowError(f"{step_key}: {agent_name} returned tool-call JSON instead of artifact content.")
        if "No specification found" in output:
            raise WorkflowError(f"{step_key}: {agent_name} did not treat the prompt file as the task.")
        write_text(output_dir / artifact, output + "\n")
        await self._publish_status(run["id"], agent_name, step_key, f"Finished writing output/{artifact}.")
        await self.log(run, f"{step_key}: wrote output/{artifact}")
        await self.refresh_artifacts(run["id"])
        return output


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
    def _harden_prompt_for_step(step_key: str, prompt: str) -> str:
        base_guard = """

Workspace safety guard:
- Current working directory is the selected Project Path.
- You may read files anywhere when needed for context.
- You must only create, modify, delete, or rename files inside the selected Project Path.
- Do not write absolute paths, parent-directory paths, `.git`, `.qwen`, `opencode.json`, `.ai-workflow`, or `.qwen-workflow`.
- Do not run dangerous commands, `git commit`, `git push`, installs, deletes, or any command that changes repository history, remote state, or files outside the project.
- Use the CLI file edit/write tools to change files directly when this step creates/modifies project files.
"""
        if step_key == "build":
            step_guard = """

Build output guard:
- You are in the Build step. Use file edit/write tools to create or modify production project files directly.
- Do not output, copy, rewrite, summarize, or include test file blocks.
- Do not write paths under tests/ and do not write files named test_*.py.
- Do not output platform file blocks for any workflow. Directly edit the project files instead.
- The project must contain at least one changed non-test production file that implements the current Requirement.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "auto_generation":
            step_guard = """

Adaptive generation output guard:
- You are in the Auto Generation Workflow step.
- Use file edit/write tools to materialize the requested project change directly.
- If direct editing is unavailable, stop and explain which edit tool was unavailable; do not return file blocks.
- You may include production files, tests, and small project documentation when useful.
- Existing validation scripts are read-only unless the user explicitly asked to modify them.
- The project must contain at least one changed file for this task.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "generate_tests":
            step_guard = """

Generate Tests output guard:
- You are in the Generate Tests step. Use file edit/write tools to create or modify test files directly.
- For Python projects, write only tests/test_*.py or tests/conftest.py.
- Do not modify production files in this step.
- Do not output platform file blocks for any workflow. Directly edit tests under tests/ instead.
"""
            return prompt.rstrip() + base_guard + step_guard
        return prompt.rstrip() + base_guard

    def _session_id_for_agent(self, run: dict[str, Any], agent_name: str) -> str | None:
        provider_sessions = run.get("agent_session_ids") or {}
        if isinstance(provider_sessions, dict) and provider_sessions.get(agent_name):
            return provider_sessions.get(agent_name)
        if agent_name == "qwen":
            return run.get("qwen_session_id")
        return run.get("agent_session_id")

    async def _publish_status(self, run_id: str, agent_name: str, step_key: str, message: str) -> None:
        await self.bus.publish(run_id, {"type": "agent_status", "agent": agent_name, "step": step_key, "message": message})
        if agent_name == "qwen":
            await self.bus.publish(run_id, {"type": "qwen_status", "step": step_key, "message": message})
