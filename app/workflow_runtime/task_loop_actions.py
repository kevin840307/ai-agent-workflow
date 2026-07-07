from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.paths import read_text, write_text
from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import (
    existing_validation_scripts,
    extract_build_files,
    failure_feedback_for_step,
    project_file_snapshot,
)
from .step_utils import step_config


class TaskLoopActionsMixin:

    @staticmethod
    def _ordered_task_ids(todo: str) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for match in re.finditer(r"\bTASK-\d{3}\b", todo or ""):
            task_id = match.group(0)
            if task_id not in seen:
                seen.add(task_id)
                ordered.append(task_id)
        return ordered

    @staticmethod
    def _task_title(todo: str, task_id: str) -> str:
        heading = re.search(rf"^###\s+{re.escape(task_id)}\s*:?\s*(.+?)\s*$", todo or "", flags=re.MULTILINE)
        if heading:
            return heading.group(1).strip() or task_id
        table_row = re.search(rf"^\|\s*{re.escape(task_id)}\s*\|\s*([^|]+?)\s*\|", todo or "", flags=re.MULTILINE)
        if table_row:
            return table_row.group(1).strip() or task_id
        return task_id

    def _task_section(self, todo: str, task_id: str) -> str:
        match = re.search(
            rf"^###\s+{re.escape(task_id)}\b.*?(?=^###\s+TASK-\d{{3}}\b|^##\s+|\Z)",
            todo or "",
            flags=re.MULTILINE | re.DOTALL,
        )
        return match.group(0).strip() if match else ""

    def _task_owner(self, todo: str, task_id: str) -> str:
        title = self._task_title(todo, task_id)
        section = self._task_section(todo, task_id)
        header = title.lower()
        goal_match = re.search(r"(?im)^\s*-\s*goal:\s*(.+)$", section or "")
        goal = goal_match.group(1).lower() if goal_match else ""
        primary = f"{header}\n{goal}"
        text = f"{primary}\n{section}".lower()
        change_pattern = r"\b(implement|create|modify|update|write|add|generate|produce|build)\b"
        if re.search(change_pattern, primary) or re.search(r"(實作|新增|建立|修改|產生|製作)", primary):
            if not re.search(r"\btests?\b", primary) and "測試" not in primary:
                return "build"
        if re.search(r"\b(generate|create|write|add)\s+(focused\s+)?(automated\s+)?tests?\b", primary) or "test files only" in text:
            return "generate_tests"
        if "external validation" in primary and not re.search(r"\b(implement|create|modify|update|write|add|build)\b", primary):
            return "run_external_validation"
        if re.search(r"\b(review|analyze|analyse|inspect|scan|understand|plan)\b", primary) and not re.search(change_pattern, primary):
            return "planning"
        return "build"

    @staticmethod
    def _fallback_validation_scripts(run: dict[str, Any]) -> list[str]:
        for step in run.get("steps") or []:
            if step.get("key") not in {"run_external_validation", "python_gate", "ai_review"}:
                continue
            config = {**step, **step_config(step)}
            value = config.get("fallbackValidationScripts") or config.get("fallback_validation_scripts") or []
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _todo_owned_validation_targets(run: dict[str, Any], todo: str) -> list[str]:
        project_dir = Path(run.get("project_path") or ".").expanduser().resolve()
        protected = existing_validation_scripts(
            project_dir,
            run.get("validation_script"),
            TaskLoopActionsMixin._fallback_validation_scripts(run),
        )
        if not protected:
            return []
        task_context = todo.split("## External Validation", 1)[0]
        found: list[str] = []
        for script in sorted(protected):
            try:
                display = script.relative_to(project_dir).as_posix()
            except ValueError:
                display = str(script)
            escaped_display = re.escape(display).replace("/", r"[\\/]")
            escaped_name = re.escape(script.name)
            if re.search(rf"(?im)(^|\s|`)(?:{escaped_display}|{escaped_name})(`|\s|$)", task_context):
                found.append(display)
        return found


    def _render_task_manifest(self, todo: str) -> str:
        task_ids = self._ordered_task_ids(todo)
        build_task_ids = [task_id for task_id in task_ids if self._task_owner(todo, task_id) == "build"]
        lines = [
            "# Task Manifest",
            "",
            "Status: READY" if task_ids else "Status: EMPTY",
            "",
            "## Purpose",
            "- Deterministic summary generated from `todo.md` so Build, Generate Tests, Retry, and Final Review share the same small-task order.",
            "- This does not let AI self-approve completion; Python gates still decide pass/fail from artifacts, tests, and external validation.",
            "- Build and Generate Tests may run as a per-task loop using this manifest; final completion still depends on verifier evidence.",
            "",
            "## Small Task Order",
        ]
        if task_ids:
            for index, task_id in enumerate(task_ids, start=1):
                owner = self._task_owner(todo, task_id)
                lines.append(f"{index}. {task_id} [owner={owner}]: {self._task_title(todo, task_id)}")
        else:
            lines.append("- No TASK-xxx items found.")
        lines.extend([
            "",
            "## Build Task Order",
        ])
        if build_task_ids:
            for index, task_id in enumerate(build_task_ids, start=1):
                lines.append(f"{index}. {task_id}: {self._task_title(todo, task_id)}")
        else:
            lines.append("- No build-owned TASK items found; Build will use the full requirement as one task.")
        lines.extend([
            "",
            "## Assembly Strategy",
            "- Implement small build-owned tasks in the listed order.",
            "- After each build-owned task, verify that the CLI agent directly changed only that task's production files under Project Path.",
            "- After all small tasks are implemented, aggregate task outputs into `output/build-result.md` and run generated tests against the assembled project state.",
            "- Generate Tests should create focused tests for task-level acceptance criteria and the assembled behavior.",
            "- Run Test and External Validation are the source of truth for completion.",
            "",
            "## Retry Strategy",
            "- On failure, retry the owner step with concrete failure feedback.",
            "- Repeated errors are allowed to continue until max retries because small/local models may recover on later attempts.",
            "- When the same error repeats multiple times, the retry prompt should switch strategy instead of repeating the same output.",
            "- Workspace/path violations remain hard failures because they protect isolation.",
            "",
        ])
        return "\n".join(lines)

    @staticmethod
    def _safe_task_id(task_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "-", task_id or "TASK-001")

    def _render_task_todo_file(self, todo: str, task: dict[str, Any], *, index: int, total: int) -> str:
        task_id = str(task.get("id") or f"TASK-{index:03d}")
        task_title = str(task.get("title") or self._task_title(todo, task_id) or task_id)
        owner = str(task.get("owner") or self._task_owner(todo, task_id) or "build")
        section = self._task_section(todo, task_id).strip()
        if not section:
            section = f"### {task_id}: {task_title}\n- Goal: Complete this small task.\n- Acceptance Criteria:\n  - AC-001: The task output satisfies the user requirement.\n"
        lines = [
            f"# {task_id}: {task_title}",
            "",
            "Status: READY",
            "",
            "## Execution Scope",
            f"- Task ID: {task_id}",
            f"- Task index: {index}/{total}",
            f"- Owner step: {owner}",
            "- This file is the only task TODO that the current build/test loop should treat as active.",
            "- Do not implement unrelated TASK items unless they are already completed dependencies required by this task.",
            "",
            "## Source Task Section",
            "",
            section,
            "",
            "## Hard Rules",
            "- Follow the user requirement, project index, architecture, and this task TODO.",
            "- Keep writes inside the selected Project path only.",
            "- Build step must output production/project artifacts only, not tests.",
            "- Generate Tests step must output tests only, not production files.",
            "- Existing validation scripts are read-only acceptance tools unless the user explicitly asks to modify them.",
            "- Git commit and git push are forbidden; the user reviews git diff manually.",
            "",
            "## Completion Evidence",
            "- The task is complete only when the CLI agent directly changes project files and later tests/validation pass.",
            "- AI review can warn about risks, but Python verifier/test/validation decide final status.",
            "",
        ]
        return "\n".join(lines)

    def _write_task_todo_files(self, output_dir: Path, todo: str, manifest: str) -> list[str]:
        tasks = self._task_entries_from_manifest(manifest)
        if not tasks and re.search(r"\bTASK-\d{3}\b", todo or ""):
            tasks = [{"id": task_id, "owner": self._task_owner(todo, task_id), "title": self._task_title(todo, task_id)} for task_id in self._ordered_task_ids(todo)]
        todo_dir = output_dir / "todos"
        todo_dir.mkdir(parents=True, exist_ok=True)
        expected_names: set[str] = set()
        written: list[str] = []
        total = len(tasks)
        for index, task in enumerate(tasks, start=1):
            task_id = str(task.get("id") or f"TASK-{index:03d}")
            filename = f"{self._safe_task_id(task_id)}.md"
            expected_names.add(filename)
            content = self._render_task_todo_file(todo, task, index=index, total=total)
            write_text(todo_dir / filename, content)
            written.append(f"output/todos/{filename}")
        for path in todo_dir.glob("TASK-*.md"):
            if path.name not in expected_names:
                path.unlink()
        index_lines = [
            "# Task Todo Index",
            "",
            "Status: READY" if written else "Status: EMPTY",
            "",
            "Each file below is the scoped TODO for one task. Build and Generate Tests should treat only the current task file as active context.",
            "",
        ]
        if written:
            index_lines.extend(f"- {item}" for item in written)
        else:
            index_lines.append("- No task TODO files were generated.")
        write_text(output_dir / "todos" / "INDEX.md", "\n".join(index_lines) + "\n")
        return written

    @staticmethod
    def _task_entries_from_manifest(manifest: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(r"^\s*\d+\.\s+(TASK-\d{3})(?:\s+\[owner=([^\]]+)\])?:\s*(.+?)\s*$", re.MULTILINE)
        for match in pattern.finditer(manifest or ""):
            task_owner = (match.group(2) or "build").strip()
            if owner and task_owner != owner:
                continue
            key = (match.group(1), task_owner)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"id": match.group(1), "owner": task_owner, "title": match.group(3).strip()})
        return entries

    def _task_run(self, run: dict[str, Any], task: dict[str, Any], *, index: int, total: int, phase: str) -> dict[str, Any]:
        scoped = dict(run)
        # Keep all task-loop retries in the same agent session.  The controller
        # only changes the prompt it sends; it does not replace the CLI agent's
        # own conversation, planning, editing, or repair behavior.
        task_id = str(task.get("id") or "TASK-001")
        scoped["_current_task"] = {
            "id": task_id,
            "title": task.get("title", "Full requested change"),
            "owner": task.get("owner", "build"),
            "index": index,
            "total": total,
            "phase": phase,
            "todo_path": f"output/todos/{self._safe_task_id(task_id)}.md",
        }
        return scoped

    @staticmethod
    def _task_output_artifact(task_id: str, filename: str) -> str:
        return f"tasks/{TaskLoopActionsMixin._safe_task_id(task_id)}/{filename}"

    @staticmethod
    def _render_aggregated_task_outputs(title: str, task_artifacts: list[tuple[str, str, str]]) -> str:
        lines = [f"# {title}", "", "Status: READY", "", "## Per-Task Outputs"]
        for task_id, task_title, content in task_artifacts:
            lines.extend(["", f"### {task_id}: {task_title}", "", content.strip(), ""])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_direct_edit_summary(title: str, task_id: str, task_title: str, files: list[tuple[str, str]]) -> str:
        lines = [
            f"# {title}",
            "",
            "Status: READY",
            "",
            f"## Task",
            f"- ID: {task_id}",
            f"- Title: {task_title}",
            "",
            "## Direct Agent Edits",
        ]
        for rel_path, content in files:
            markers = TaskLoopActionsMixin._content_markers(content)
            marker_text = ", ".join(markers[:8]) if markers else "none detected"
            normalized_rel_path = str(rel_path).replace(chr(92), "/")
            lines.extend([
                f"- `{normalized_rel_path}`",
                f"  - Size: {len(content)} chars",
                f"  - Markers: {marker_text}",
            ])
        lines.extend(["", "The agent modified the project files directly. The platform recorded this summary from the before/after project snapshot and did not materialize FILE blocks."])
        return "\n".join(lines).rstrip() + "\n"


    def _build_step_feedback(self, run: dict[str, Any]) -> str:
        input_dir = Path(run["workspace"]) / "input"
        return failure_feedback_for_step(read_text(input_dir / "failure-feedback.md"), "build")

    @staticmethod
    def _feedback_mentions_task(feedback: str, task_id: str) -> bool:
        if not feedback.strip() or not task_id.strip():
            return False
        return task_id in feedback or bool(re.search(rf"\btask\s+{re.escape(task_id)}\b", feedback, flags=re.I))

    @staticmethod
    def _retry_feedback_blocks(feedback: str) -> list[str]:
        if not feedback.strip():
            return []
        return [
            match.group(0).strip()
            for match in re.finditer(
                r"^## Retry Feedback for .*?(?=^## Retry Feedback for |\Z)",
                feedback,
                flags=re.MULTILINE | re.DOTALL,
            )
        ]

    @classmethod
    def _latest_retry_feedback_block(cls, feedback: str) -> str:
        blocks = cls._retry_feedback_blocks(feedback)
        return blocks[-1] if blocks else ""

    @classmethod
    def _latest_feedback_task_id(cls, feedback: str) -> str:
        block = cls._latest_retry_feedback_block(feedback)
        if not block:
            return ""
        match = re.search(r"\bTASK-\d{3}\b", block)
        return match.group(0) if match else ""

    @classmethod
    def _latest_feedback_mentions_task(cls, feedback: str, task_id: str) -> bool:
        block = cls._latest_retry_feedback_block(feedback)
        return cls._feedback_mentions_task(block, task_id)

    @staticmethod
    def _feedback_is_generic_for_task_loop(feedback: str) -> bool:
        block = TaskLoopActionsMixin._latest_retry_feedback_block(feedback)
        return bool(block.strip()) and not bool(re.search(r"\bTASK-\d{3}\b", block))

    @staticmethod
    def _with_generic_repair_task(tasks: list[dict[str, Any]], *, owner: str) -> list[dict[str, Any]]:
        used_ids = {str(task.get("id") or "") for task in tasks}
        repair_id = ""
        for number in range(999, 899, -1):
            candidate = f"TASK-{number:03d}"
            if candidate not in used_ids:
                repair_id = candidate
                break
        if not repair_id:
            repair_id = "TASK-REPAIR"
        return [
            *tasks,
            {
                "id": repair_id,
                "owner": owner,
                "title": "Repair assembled project from latest workflow failure feedback",
                "_generic_repair_task": True,
            },
        ]

    @staticmethod
    def _content_markers(content: str) -> list[str]:
        markers: list[str] = []
        patterns = [
            r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
            r"^\s*class\s+([A-Za-z_]\w*)\b",
            r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
            r"^\s*#{1,6}\s+(.+?)\s*$",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, content or "", flags=re.MULTILINE):
                marker = str(match.group(1)).strip()
                if marker and marker not in markers:
                    markers.append(marker)
        return markers[:40]

    @staticmethod
    def _task_state_path(output_dir: Path, task_id: str, phase: str) -> Path:
        safe_task_id = "".join(ch if ch.isalnum() or ch in {"_", ".", "-"} else "-" for ch in str(task_id or "TASK-000"))
        return output_dir / "tasks" / safe_task_id / f"{phase}-state.json"

    def _write_task_direct_state(self, output_dir: Path, project_dir: Path, task_id: str, phase: str, files: list[tuple[str, str]]) -> None:
        state_files: list[dict[str, Any]] = []
        for rel_path, content in files:
            markers = self._content_markers(content)
            state_files.append({"path": rel_path.replace("\\", "/"), "markers": markers})
        path = self._task_state_path(output_dir, task_id, phase)
        write_text(path, json.dumps({"task_id": task_id, "phase": phase, "files": state_files}, indent=2, ensure_ascii=False))

    def _task_direct_state_is_satisfied(self, output_dir: Path, project_dir: Path, task_id: str, phase: str) -> bool:
        path = self._task_state_path(output_dir, task_id, phase)
        if not path.is_file():
            return False
        try:
            state = json.loads(read_text(path))
        except json.JSONDecodeError:
            return False
        files = state.get("files") if isinstance(state, dict) else []
        if not isinstance(files, list) or not files:
            return False
        for item in files:
            if not isinstance(item, dict):
                return False
            rel_path = str(item.get("path") or "").strip().replace("\\", "/")
            markers = [str(marker) for marker in item.get("markers") or [] if str(marker).strip()]
            if not rel_path:
                return False
            target = project_dir / rel_path
            if not target.is_file():
                return False
            try:
                actual = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                return False
            if any(marker not in actual for marker in markers):
                return False
        return True

    def _validate_previous_direct_task_states_preserved(
        self,
        output_dir: Path,
        project_dir: Path,
        *,
        current_index: int,
        current_task_id: str,
        phase: str,
    ) -> None:
        missing: list[str] = []
        for task_dir in sorted(path for path in (output_dir / "tasks").glob("TASK-*") if path.is_dir()):
            match = re.fullmatch(r"TASK-(\d{3})", task_dir.name)
            if not match:
                continue
            task_number = int(match.group(1))
            if not current_index or task_number >= current_index:
                continue
            state_path = task_dir / f"{phase}-state.json"
            if not state_path.is_file():
                continue
            try:
                state = json.loads(read_text(state_path))
            except json.JSONDecodeError:
                continue
            for item in state.get("files") or []:
                if not isinstance(item, dict):
                    continue
                rel_path = str(item.get("path") or "").strip().replace("\\", "/")
                markers = [str(marker) for marker in item.get("markers") or [] if str(marker).strip()]
                if not rel_path or not markers:
                    continue
                target = project_dir / rel_path
                if not target.is_file():
                    missing.append(f"{current_task_id} removed previous task file {rel_path} from {task_dir.name}")
                    continue
                try:
                    actual = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                lost = [marker for marker in markers if marker not in actual]
                if lost:
                    missing.append(
                        f"{current_task_id} changed {rel_path} and lost previous marker(s) from {task_dir.name}: {', '.join(lost[:8])}"
                    )
        if missing:
            raise WorkflowError(
                "A direct agent edit removed previously completed task behavior. "
                "Retry the current task and preserve earlier task results. " + "; ".join(missing)
            )

    def _task_artifact_is_satisfied(self, project_dir: Path, artifact_path: Path) -> bool:
        files = extract_build_files(read_text(artifact_path))
        if not files:
            return False
        for rel_path, expected in files:
            target = project_dir / rel_path.strip().strip("`").replace("\\", "/")
            if not target.is_file():
                return False
            try:
                actual = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                return False
            markers = self._content_markers(expected)
            if markers:
                if any(marker not in actual for marker in markers):
                    return False
            elif actual != expected:
                return False
        return True

    def _previous_task_artifacts(self, output_dir: Path, current_index: int, filename: str) -> list[tuple[str, Path]]:
        artifacts: list[tuple[str, Path]] = []
        task_root = output_dir / "tasks"
        if not task_root.exists():
            return artifacts
        for task_dir in sorted(path for path in task_root.iterdir() if path.is_dir()):
            match = re.fullmatch(r"TASK-(\d{3})", task_dir.name)
            if not match:
                continue
            if int(match.group(1)) >= current_index:
                continue
            artifact_path = task_dir / filename
            if artifact_path.is_file():
                artifacts.append((task_dir.name, artifact_path))
        return artifacts

    def _validate_previous_task_markers_preserved(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_task_id: str,
        current_index: int,
        current_files: list[tuple[str, str]],
        filename: str,
    ) -> None:
        changed_paths = {rel_path.strip().strip("`").replace("\\", "/") for rel_path, _ in current_files}
        if not changed_paths:
            return
        missing: list[str] = []
        for previous_task_id, artifact_path in self._previous_task_artifacts(output_dir, current_index, filename):
            for rel_path, previous_content in extract_build_files(read_text(artifact_path)):
                normalized = rel_path.strip().strip("`").replace("\\", "/")
                if normalized not in changed_paths:
                    continue
                markers = self._content_markers(previous_content)
                if not markers:
                    continue
                target = project_dir / normalized
                try:
                    actual = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    actual = ""
                lost = [marker for marker in markers if marker not in actual]
                if lost:
                    missing.append(
                        f"{current_task_id} overwrote previous task output from {previous_task_id} in {normalized}; "
                        f"missing preserved marker(s): {', '.join(lost[:8])}"
                    )
        if missing:
            raise WorkflowError(
                "Task output appears to have overwritten already completed task behavior. "
                "When editing a shared file, output the complete file and preserve previous task results. "
                + "; ".join(missing)
            )

    @staticmethod
    def _loose_code_from_agent_output(output: str) -> str:
        text = (output or "").strip()
        if not text or "FILE:" in text:
            return ""
        fences = list(re.finditer(r"```(?P<lang>[A-Za-z0-9_.+-]*)\s*\r?\n(?P<body>.*?)\r?\n```", text, flags=re.DOTALL))
        if fences:
            # Prefer an explicit source-code fence.  Ignore prose-only markdown fences.
            for match in reversed(fences):
                lang = (match.group("lang") or "").lower()
                body = match.group("body").strip()
                if lang in {"python", "py", "javascript", "js", "typescript", "ts", "java", "csharp", "cs", "go", "rust", "rs"}:
                    return body.rstrip() + "\n"
            if len(fences) == 1:
                body = fences[0].group("body").strip()
                if re.search(r"(?m)^\s*(?:def|class|import|from)\s+", body):
                    return body.rstrip() + "\n"
            return ""
        if re.search(r"(?m)^\s*(?:def|class|import|from)\s+", text):
            return text.rstrip() + "\n"
        return ""

    @staticmethod
    def _is_python_like_code(content: str) -> bool:
        return bool(re.search(r"(?m)^\s*(?:def|class|import|from)\s+", content or ""))

    @staticmethod
    def _sanitized_module_name(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", (name or "main").strip().lower()).strip("_")
        return cleaned or "main"

    def _preferred_loose_output_path(self, project_dir: Path, output_dir: Path, current_index: int, filename: str, content: str) -> str:
        # A model that omits FILE blocks usually emitted a fragment for the same
        # shared file used by earlier tasks.  Prefer the most recent earlier
        # production path so the task loop converges instead of restarting from
        # TASK-001.
        previous = self._previous_task_artifacts(output_dir, current_index, filename)
        for _task_id, artifact_path in reversed(previous):
            paths = [rel_path.strip().strip("`").replace("\\", "/") for rel_path, _ in extract_build_files(read_text(artifact_path))]
            for rel_path in reversed(paths):
                if rel_path and not rel_path.startswith("tests/"):
                    return rel_path
        snapshot = project_file_snapshot(project_dir)
        source_paths = [path.replace("\\", "/") for path in sorted(snapshot) if not path.replace("\\", "/").startswith("tests/") and Path(path).suffix.lower() in {".py", ".js", ".ts", ".java", ".cs", ".go", ".rs"}]
        if len(source_paths) == 1:
            return source_paths[0]
        if self._is_python_like_code(content):
            return f"src/{self._sanitized_module_name(project_dir.name)}.py"
        return "src/main.txt"

    def _coerce_loose_task_output_to_files(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_index: int,
        filename: str,
        output: str,
    ) -> list[tuple[str, str]]:
        code = self._loose_code_from_agent_output(output)
        if not code:
            return []
        rel_path = self._preferred_loose_output_path(project_dir, output_dir, current_index, filename, code)
        target = project_dir / rel_path
        content = code.rstrip() + "\n"
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                existing = ""
            existing_markers = self._content_markers(existing)
            new_markers = self._content_markers(content)
            if existing.strip() and existing_markers and new_markers:
                missing_existing = [marker for marker in existing_markers if marker not in content]
                novel_new = [marker for marker in new_markers if marker not in existing]
                if missing_existing and novel_new:
                    content = existing.rstrip() + "\n\n" + content.lstrip()
        return [(rel_path, content)]

    def _merge_candidate_with_existing_if_needed(
        self,
        project_dir: Path,
        output_dir: Path,
        *,
        current_index: int,
        files: list[tuple[str, str]],
        filename: str,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        adjusted: list[tuple[str, str]] = []
        notes: list[str] = []
        for rel_path, content in files:
            normalized = rel_path.strip().strip("`").replace("\\", "/")
            expected_markers: list[str] = []
            for _previous_task_id, artifact_path in self._previous_task_artifacts(output_dir, current_index, filename):
                for previous_rel, previous_content in extract_build_files(read_text(artifact_path)):
                    if previous_rel.strip().strip("`").replace("\\", "/") != normalized:
                        continue
                    for marker in self._content_markers(previous_content):
                        if marker not in expected_markers:
                            expected_markers.append(marker)
            missing = [marker for marker in expected_markers if marker not in content]
            target = project_dir / normalized
            if missing and target.is_file():
                try:
                    existing = target.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    existing = ""
                new_markers = [marker for marker in self._content_markers(content) if marker not in existing]
                if existing.strip() and new_markers:
                    merged = existing.rstrip() + "\n\n" + content.lstrip().rstrip() + "\n"
                    adjusted.append((rel_path, merged))
                    notes.append(f"{normalized} preserved previous marker(s): {', '.join(missing[:6])}")
                    continue
            adjusted.append((rel_path, content))
        return adjusted, notes

