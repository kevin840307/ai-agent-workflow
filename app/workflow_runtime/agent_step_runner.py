from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_errors import UserInputRequired, WorkflowError
from app.runtime_paths import read_text, write_text

from .agents import AgentManager, AgentRequest
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
    ) -> None:
        output_dir = Path(run["workspace"]) / "output"
        input_dir = Path(run["workspace"]) / "input"
        step_config = next((step for step in run.get("steps", []) if step.get("key") == step_key), {})
        agent = self.agent_manager.resolve(step_config.get("config") or {}, agent_name=agent_name or step_config.get("agent"))
        agent_name = agent.name
        prompt_result = self.prompt_builder.build(
            run,
            step_key,
            prompt_name,
            allow_interaction=allow_interaction,
            agent_name=agent_name,
        )
        cwd = Path(run.get("project_path") or run["workspace"])
        session_id = self._session_id_for_agent(run, agent_name)
        request = AgentRequest(
            run_id=run["id"],
            step_key=step_key,
            prompt=prompt_result.prompt,
            cwd=cwd,
            session_id=session_id,
        )
        display_cmd = agent.command_preview(request)
        await self.log(run, f"{step_key}: agent={agent_name}, command=`{display_cmd}`, cwd={cwd}")
        await self.log(run, f"{step_key}: prompt length={len(prompt_result.prompt)} chars, passed by file={prompt_result.relative_prompt_path}")
        if prompt_result.skill_files:
            await self.log(run, f"{step_key}: selected skills: {', '.join(path.parent.name for path in prompt_result.skill_files)}")
        await self.log(run, f"{step_key}: prompt saved to {prompt_result.relative_prompt_path}")
        await self.refresh_artifacts(run["id"])
        await self._publish_status(run["id"], agent_name, step_key, f"{agent_name} is running...")

        async def publish_agent_output(stream: str, text: str) -> None:
            if not text:
                return
            await self.bus.publish(run["id"], {"type": "agent_output", "agent": agent_name, "step": step_key, "stream": stream, "text": text})
            # Legacy UI compatibility while migrating frontend event names.
            if agent_name == "qwen":
                await self.bus.publish(run["id"], {"type": "qwen_output", "step": step_key, "stream": stream, "text": text})

        result = await agent.run_stream(request, on_output=publish_agent_output)
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
        await self._publish_status(run["id"], agent_name, step_key, f"Wrote output/{artifact}")
        await self.log(run, f"{step_key}: wrote output/{artifact}")
        await self.refresh_artifacts(run["id"])

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
