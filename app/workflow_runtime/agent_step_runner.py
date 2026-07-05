from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.runtime_modules.errors import UserInputRequired, WorkflowError
from app.runtime_modules.files import failure_feedback_for_step
from app.core.paths import read_text, write_text
from app.security.agent_project_config import ensure_agent_project_configs
from app.security.workspace_guard import resolve_project_relative_write

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
        if self._is_compact_retry_prompt(prompt_text):
            await self.log(run, f"{step_key}: compact retry prompt enabled because agent session is being reused")
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
        file_block_output = self._tool_call_file_blocks(output, cwd)
        if file_block_output:
            output = file_block_output
        tool_name = self._tool_call_name(output)
        if tool_name:
            write_text(output_dir / artifact, output + "\n")
            raise WorkflowError(f"{step_key}: {agent_name} returned tool-call JSON `{tool_name}` instead of artifact content.")
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
    def _is_compact_retry_prompt(prompt: str) -> bool:
        return prompt.lstrip().startswith("# Compact Reuse Retry")

    @staticmethod
    def _tool_call_name(output: str) -> str:
        text = (output or "").strip()
        if not text:
            return ""
        parsed = AgentStepRunner._tool_call_payload(text)
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
            return parsed["name"].strip()
        match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _tool_call_payload(output: str) -> Any:
        text = (output or "").strip()
        if text.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            relaxed = AgentStepRunner._json_with_triple_quoted_strings(text)
            if relaxed != text:
                try:
                    return json.loads(relaxed)
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _json_with_triple_quoted_strings(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            prefix = match.group(1)
            content = match.group(2)
            return prefix + json.dumps(content)

        return re.sub(r'(:\s*)"""(.*?)"""', replace, text, flags=re.DOTALL)

    @staticmethod
    def _tool_call_file_blocks(output: str, cwd: Path) -> str:
        payload = AgentStepRunner._tool_call_payload(output)
        if not isinstance(payload, dict):
            return AgentStepRunner._loose_tool_call_file_blocks(output, cwd)
        args = AgentStepRunner._tool_call_arguments(payload)
        if not isinstance(args, dict):
            return AgentStepRunner._loose_tool_call_file_blocks(output, cwd)
        candidates: list[dict[str, Any]]
        file_items = (
            args.get("files")
            or args.get("edits")
            or args.get("changes")
            or args.get("writes")
        )
        if isinstance(file_items, list):
            candidates = [item for item in file_items if isinstance(item, dict)]
        else:
            candidates = [args]
        blocks: list[str] = []
        for item in candidates:
            raw_path = AgentStepRunner._tool_call_path(item)
            content = AgentStepRunner._tool_call_content(item)
            if not raw_path and content is not None:
                parsed = AgentStepRunner._path_prefixed_content(str(content))
                if parsed:
                    raw_path, content = parsed
            if not raw_path or content is None:
                continue
            rel_path = AgentStepRunner._safe_tool_call_relative_path(cwd, str(raw_path))
            if not rel_path:
                continue
            blocks.extend(["", f"FILE: {rel_path}", "CONTENT:", str(content).rstrip(), "END_FILE"])
        if not blocks:
            return ""
        name = payload.get("name") or "tool_call"
        return "\n".join(["# Tool Call File Blocks", "", f"Converted from agent tool-call JSON: `{name}`.", *blocks]).strip()

    @staticmethod
    def _loose_tool_call_file_blocks(output: str, cwd: Path) -> str:
        text = (output or "").strip()
        if not text:
            return ""
        name_match = re.search(r'"name"\s*:\s*"([^"]+)"', text)
        content_match = re.search(
            r'"(?:new_source|newSource|content|contents|source|text|data)"\s*:\s*(?:"""(.*?)"""|"([\s\S]*?)")',
            text,
            flags=re.DOTALL,
        )
        if not content_match:
            return ""
        content = content_match.group(1) if content_match.group(1) is not None else content_match.group(2)
        parsed = AgentStepRunner._path_prefixed_content(content)
        if not parsed:
            return ""
        raw_path, body = parsed
        rel_path = AgentStepRunner._safe_tool_call_relative_path(cwd, str(raw_path))
        if not rel_path:
            return ""
        name = name_match.group(1).strip() if name_match else "tool_call"
        return "\n".join(
            [
                "# Tool Call File Blocks",
                "",
                f"Converted from agent tool-call JSON: `{name}`.",
                "",
                f"FILE: {rel_path}",
                "CONTENT:",
                str(body).rstrip(),
                "END_FILE",
            ]
        ).strip()

    @staticmethod
    def _path_prefixed_content(content: str) -> tuple[str, str] | None:
        text = (content or "").strip("\n\r ")
        if not text:
            return None
        match = re.match(r"^\s*([A-Za-z0-9_.\-/\\]+)\s*:\s*(.*)$", text, flags=re.DOTALL)
        if not match:
            return None
        raw_path = match.group(1).strip()
        body = match.group(2)
        if not raw_path or "." not in Path(raw_path).name:
            return None
        return raw_path, body.lstrip()

    @staticmethod
    def _tool_call_arguments(payload: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("arguments", "args", "parameters", "input"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        if AgentStepRunner._tool_call_path(payload) is not None:
            return payload
        return None

    @staticmethod
    def _tool_call_path(item: dict[str, Any]) -> Any:
        for key in (
            "file_path",
            "filepath",
            "filePath",
            "path",
            "file",
            "filename",
            "target_file",
            "targetPath",
            "target_path",
        ):
            value = item.get(key)
            if value:
                return value
        return None

    @staticmethod
    def _tool_call_content(item: dict[str, Any]) -> Any:
        for key in (
            "new_source",
            "newSource",
            "content",
            "contents",
            "source",
            "text",
            "data",
        ):
            if key in item and item.get(key) is not None:
                return item.get(key)
        return None

    @staticmethod
    def _safe_tool_call_relative_path(cwd: Path, raw_path: str) -> str:
        try:
            root = cwd.expanduser().resolve()
            resolved = resolve_project_relative_write(root, raw_path, label="agent tool-call file")
            rel = resolved.relative_to(root).as_posix()
        except (OSError, ValueError, WorkflowError):
            return ""
        if not rel or rel.startswith("../") or rel in {".", ".."}:
            return ""
        if rel.startswith((".git/", ".qwen/", ".ai-workflow/", ".qwen-workflow/")) or rel == "opencode.json":
            return ""
        return rel

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
                "- Do not output tool-call JSON or call tools such as use_exit_plan_mode; this workflow expects artifact text, direct edits, or FILE/CONTENT/END_FILE blocks.",
                "- If the previous failure says tool-call JSON, edit_file, write_file, open_code, enter_plan_mode, exit_plan_mode, or empty output, stop using tool-call JSON entirely for this retry.",
                "- In that case, output only complete file blocks in this exact shape:",
                "  FILE: relative/path/to/file.ext",
                "  CONTENT:",
                "  complete file content",
                "  END_FILE",
                "- Put only a relative path on the FILE line. Never put absolute paths, drive-stripped absolute paths, prose, bullets, or code on the FILE line.",
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
- If tool use would be returned as JSON such as `{"name": "edit_file"}`, do not use that tool call; output complete FILE/CONTENT/END_FILE blocks instead.
"""
        if step_key == "build":
            step_guard = """

Build output guard:
- You are in the Build step. Create or modify production project files directly, or output FILE/CONTENT/END_FILE blocks for the platform to materialize.
- Do not output, copy, rewrite, summarize, or include test file blocks.
- Do not write paths under tests/ and do not write files named test_*.py.
- Do not return edit tool JSON. If direct editing is unavailable or would emit JSON, output only FILE/CONTENT/END_FILE blocks for production files.
- The project must contain at least one non-test production file that implements the current Requirement.
"""
            return prompt.rstrip() + base_guard + step_guard
        if step_key == "auto_generation":
            step_guard = """

Adaptive generation output guard:
- You are in the Auto Generation Workflow step.
- Materialize the requested project change directly, or output FILE/CONTENT/END_FILE blocks for the platform to materialize.
- Do not return edit tool JSON. If direct editing is unavailable or would emit JSON, output only FILE/CONTENT/END_FILE blocks for the files needed by this task.
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
- You are in the Generate Tests step. Create or modify test files directly, or output FILE/CONTENT/END_FILE blocks for the platform to materialize.
- For Python projects, write only tests/test_*.py or tests/conftest.py.
- Do not modify production files in this step.
- Do not return edit tool JSON. If direct editing is unavailable or would emit JSON, output only FILE/CONTENT/END_FILE blocks under tests/.
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
