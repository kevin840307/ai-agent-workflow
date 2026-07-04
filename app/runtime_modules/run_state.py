from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.paths import read_text, utc_now, write_text

MAX_RUN_LOG_CHARS = 250_000


def artifact_record(run_id: str, run_dir: Path, rel_path: str) -> dict[str, Any]:
    path = run_dir / rel_path
    return {
        "id": f"{run_id}:{rel_path.replace('/', '|')}",
        "name": Path(rel_path).name,
        "path": rel_path,
        "size": path.stat().st_size if path.exists() else 0,
        "updated_at": utc_now(),
    }




def classify_repair_error(source_key: str, target_key: str, error: str) -> str:
    text = (error or "").lower()
    if "outside project path" in text or "unsafe" in text or "parent-directory" in text or "absolute path" in text:
        return "PATH_VIOLATION"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "did not return any production file/content/end_file" in text or "no file blocks" in text or "file/content/end_file" in text and "did not" in text:
        return "NO_FILE_OUTPUT"
    if "did not create any test files" in text or "did not create test" in text or "generate_tests can only write" in text:
        return "NO_TEST_GENERATED"
    if "did not create or modify" in text or "project changes" in text:
        return "NO_PRODUCTION_CHANGE"
    if "syntaxerror" in text or "invalid python syntax" in text or "parse" in text and source_key == "generate_tests":
        return "SYNTAX_ERROR"
    if source_key == "run_test" or "test command failed" in text or "failed" in text and "pytest" in text:
        return "TEST_FAILED"
    if source_key == "run_external_validation" or "validation" in text and "failed" in text:
        return "VALIDATION_FAILED"
    if "tool-call json" in text or "artifact content" in text or "returned empty" in text:
        return "AGENT_OUTPUT_FORMAT"
    return "UNKNOWN"


def repair_strategy_for_class(error_class: str) -> str:
    return {
        "PATH_VIOLATION": "Rewrite only relative FILE paths inside Project Path; do not retry unsafe path tricks.",
        "TIMEOUT": "Reduce scope, simplify implementation, and avoid long-running commands.",
        "NO_FILE_OUTPUT": "Use Qwen/OpenCode direct edits for the owner step; do not return file blocks.",
        "NO_TEST_GENERATED": "Return focused test platform file blocks only under tests/.",
        "NO_PRODUCTION_CHANGE": "Modify or create the intended production/project artifact instead of restating the plan.",
        "SYNTAX_ERROR": "Fix the exact syntax/import error and keep the patch minimal.",
        "TEST_FAILED": "Use failing assertions/stdout/stderr to repair production code first; change tests only when they are clearly invalid.",
        "VALIDATION_FAILED": "Treat the validation script as the acceptance oracle and repair production outputs until it exits 0.",
        "AGENT_OUTPUT_FORMAT": "Output artifact text only; do not return tool-call JSON or empty output.",
    }.get(error_class, "Use the concrete failure text, previous artifacts, and verifier evidence to choose a different repair strategy.")

def retry_recovery_notes(source_key: str, target_key: str, error: str) -> list[str]:
    """Return workflow-level recovery notes for the next retry prompt.

    Keep this step-oriented rather than domain-oriented. It must never infer or
    generate application behavior; it only tells the next agent pass where to
    look and what acceptance gate failed.
    """
    text = (error or "").lower()
    error_class = classify_repair_error(source_key, target_key, error)
    notes: list[str] = [
        f"Error class: {error_class}.",
        "Repair strategy: " + repair_strategy_for_class(error_class),
    ]
    if source_key == "run_test" and target_key == "generate_tests":
        notes.extend([
            "The failure appears to be in generated tests, test imports, or test syntax.",
            "Regenerate tests from the current Requirement, Architecture, Todo, and Build result; do not change production files in Generate Tests.",
        ])
    elif source_key == "run_test":
        notes.extend([
            "Automated tests failed after Build, so the implementation likely does not satisfy the generated acceptance checks.",
            "Fix production code first; change tests only if the failure feedback proves the tests are invalid.",
        ])
    elif source_key == "run_external_validation":
        notes.extend([
            "The user/project validation script is the acceptance gate and failed after tests.",
            "Read the validation output, then fix production files so the script passes. Do not edit existing validation scripts unless the user explicitly requested it.",
        ])
    elif source_key == "final_review":
        notes.extend([
            "The final completion gate failed because required verification evidence was missing or not PASS.",
            "Re-check test-result.md and external-validation-result.md, then repair the earlier step that produced the failing evidence.",
        ])
    elif source_key == "build":
        notes.extend([
            "Build did not produce acceptable production changes or file blocks.",
            "Use Qwen/OpenCode direct edits inside the selected Project Path; do not return file blocks.",
        ])
    else:
        notes.append("Retry the target step using the concrete error message and previously approved artifacts as the source of truth.")

    if "outside project path" in text or "unsafe file path" in text or "parent directory" in text:
        notes.append("Workspace isolation was enforced: writes must stay inside the selected Project Path; external paths are read-only context.")
    if "validation scripts" in text:
        notes.append("Existing validation scripts are protected acceptance tools and must not be overwritten by Build.")
    if "test file blocks" in text:
        notes.append("Build owns production files only; Generate Tests owns tests/ files only.")
    return notes


class RunState:
    def __init__(self, store, bus) -> None:
        self.store = store
        self.bus = bus

    async def update_run(self, run_id: str, fn) -> dict[str, Any] | None:
        def mut(data):
            for run in data["runs"]:
                if run["id"] == run_id:
                    fn(run)
                    return run
            return None

        return await self.store.mutate(mut)

    async def get_run_record(self, run_id: str) -> dict[str, Any]:
        from fastapi import HTTPException

        data = await self.store.read()
        run = next((item for item in data["runs"] if item["id"] == run_id), None)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    async def append_session_message(
        self,
        session_id: str,
        role: str,
        content: str,
        kind: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        import uuid

        msg = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": utc_now(),
        }
        if kind:
            msg["kind"] = kind
        msg.update({key: value for key, value in extra.items() if value is not None})

        def add(data):
            data["messages"].append(msg)
            for session in data.get("sessions", []):
                if session.get("id") == session_id:
                    session["updated_at"] = utc_now()
            return msg

        return await self.store.mutate(add)

    async def update_message(self, message_id: str, **updates: Any) -> dict[str, Any] | None:
        def apply(data):
            for msg in data.get("messages", []):
                if msg.get("id") == message_id:
                    msg.update({key: value for key, value in updates.items() if value is not None})
                    msg["updated_at"] = utc_now()
                    for session in data.get("sessions", []):
                        if session.get("id") == msg.get("session_id"):
                            session["updated_at"] = utc_now()
                    return msg
            return None

        return await self.store.mutate(apply)

    async def log(self, run: dict[str, Any], message: str) -> None:
        meta = f"run_id={run.get('id', '')} session_id={run.get('session_id', '')}"
        line = f"[{utc_now()}] {meta} {message}"
        run_dir = Path(run["workspace"])
        log_path = run_dir / ".workflow" / "run-log.md"
        previous = read_text(log_path)
        content = previous + line + "\n"
        if len(content) > MAX_RUN_LOG_CHARS:
            content = "# Log rotated: keeping latest entries only.\n" + content[-MAX_RUN_LOG_CHARS:]
        write_text(log_path, content)
        await self.bus.publish(run["id"], {"type": "log", "message": line})

    async def set_step(
        self,
        run_id: str,
        key: str,
        status: str,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        def apply(run):
            for step in run["steps"]:
                if step["key"] == key:
                    step["status"] = status
                    if status == "running":
                        step["started_at"] = utc_now()
                        step["error"] = None
                        step["error_code"] = None
                    if status in {"passed", "failed", "skipped", "waiting_input", "cancelled"}:
                        step["ended_at"] = utc_now()
                        step["error"] = error
                        step["error_code"] = error_code
            run["updated_at"] = utc_now()

        run = await self.update_run(run_id, apply)
        if run:
            await self.bus.publish(run_id, {"type": "run", "run": run})

    async def reset_steps_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        def apply(run):
            for index, step in enumerate(run["steps"]):
                if index >= start_index:
                    step["status"] = "pending"
                    step["started_at"] = None
                    step["ended_at"] = None
                    step["error"] = None
                    step["error_code"] = None
            run["status"] = "queued"
            run["error"] = None
            run["error_code"] = None
            run["ended_at"] = None
            run["updated_at"] = utc_now()

        return await self.update_run(run_id, apply)

    async def reset_retry_counts_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        def apply(run):
            for index, step in enumerate(run["steps"]):
                if index >= start_index:
                    step["retry_count"] = 0
                    step["manual_retry_started_at"] = utc_now()
            run["updated_at"] = utc_now()

        return await self.update_run(run_id, apply)

    async def get_step_retry_count(self, run_id: str, key: str) -> int:
        data = await self.store.read()
        run = next((item for item in data["runs"] if item["id"] == run_id), None)
        if not run:
            return 0
        step = next((item for item in run.get("steps", []) if item.get("key") == key), None)
        return int((step or {}).get("retry_count", 0) or 0)

    async def increment_step_retry(self, run_id: str, key: str) -> int:
        def apply(run):
            for step in run["steps"]:
                if step["key"] == key:
                    step["retry_count"] = int(step.get("retry_count", 0)) + 1
                    return step["retry_count"]
            return 0

        result = await self.store.mutate(lambda data: apply(next(run for run in data["runs"] if run["id"] == run_id)))
        run = await self.get_run_record(run_id)
        await self.bus.publish(run_id, {"type": "run", "run": run})
        return int(result or 0)

    async def append_failure_feedback(
        self,
        run: dict[str, Any],
        source_key: str,
        target_key: str,
        exc: BaseException,
        retry_count: int,
        max_retries: int,
    ) -> None:
        input_dir = Path(run["workspace"]) / "input"
        feedback_path = input_dir / "failure-feedback.md"
        previous = read_text(feedback_path)
        error = str(exc).strip()
        notes = retry_recovery_notes(source_key, target_key, error)
        entry = (
            f"## Retry Feedback for {target_key}\n\n"
            f"Submitted at: {utc_now()}\n\n"
            f"- Failed step: {source_key}\n"
            f"- Retry target: {target_key}\n"
            f"- Retry attempt: {retry_count}/{max_retries}\n"
            f"- Error class: {classify_repair_error(source_key, target_key, error)}\n"
            f"- Stop condition: retry continues through repeated errors until {target_key} reaches {max_retries}/{max_retries} attempts or all downstream gates pass.\n"
            f"- Strategy shift: if this same class repeats 3+ times, try a different implementation approach rather than reusing the same output.\n\n"
            "### Recovery analysis\n"
            + "".join(f"- {note}\n" for note in notes)
            + "\n### Error message to fix\n\n"
            f"{error}\n\n"
        )
        write_text(feedback_path, previous + ("\n" if previous.strip() else "") + entry)
        await self.record_step_event(
            run["id"],
            target_key,
            "retry",
            f"Retry {retry_count}/{max_retries} from {source_key}: {error}",
            {
                "source_step": source_key,
                "target_step": target_key,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "error": error,
                "error_class": classify_repair_error(source_key, target_key, error),
            },
        )
        await self.refresh_artifacts(run["id"])

    async def record_step_event(
        self,
        run_id: str,
        step_key: str,
        kind: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        def apply(run):
            ts = utc_now()
            event = {
                "time": ts,
                "ts": ts,
                "step_key": step_key,
                "stepKey": step_key,
                "kind": kind,
                "type": kind,
                "message": message,
            }
            if extra:
                event.update(extra)
            run.setdefault("timeline", []).append(event)
            for step in run.get("steps", []):
                if step.get("key") == step_key:
                    step.setdefault("events", []).append(event)
                    step["last_event"] = message
                    if kind == "retry":
                        step.setdefault("retry_history", []).append(event)
                    break
            run["updated_at"] = utc_now()

        run = await self.update_run(run_id, apply)
        if run:
            await self.bus.publish(run_id, {"type": "run", "run": run})

    async def refresh_artifacts(self, run_id: str) -> None:
        def apply(run):
            run_dir = Path(run["workspace"])
            rels = [
                "requirement.md",
                "input/questions.md",
                "input/answers.md",
                "input/guidance.md",
                "input/failure-feedback.md",
                "prompts/skill-context.md",
                ".workflow/run-log.md",
                ".workflow/run-summary.md",
                ".workflow/run-trace.json",
                ".workflow/state.json",
            ]

            def add_rel(value):
                raw = str(value or "").strip().replace("\\", "/")
                if not raw:
                    return
                if raw.startswith("output/") or raw.startswith("input/") or raw.startswith("prompts/") or raw.startswith(".workflow/"):
                    rels.append(raw)
                else:
                    rels.append(f"output/{raw}")

            for step in run.get("steps", []):
                config = step.get("config") or {}
                add_rel(f"prompts/{step.get('key')}.md")
                add_rel(config.get("outputFile") or config.get("filename"))
                for expected in config.get("expectedFiles") or []:
                    add_rel(expected)
                for artifact in config.get("contextArtifacts") or config.get("dependsOnArtifacts") or []:
                    add_rel(artifact)
                output_file = str(config.get("outputFile") or config.get("filename") or "").strip()
                if output_file:
                    stem = Path(output_file).stem
                    suffix = Path(output_file).suffix or ".md"
                    for index, _reviewer in enumerate(config.get("reviewers") or [], start=1):
                        add_rel(f"{stem}.reviewer-{index}{suffix}")

            for folder_name in ["input", "prompts", "output", ".workflow"]:
                folder = run_dir / folder_name
                if not folder.exists():
                    continue
                for path in folder.rglob("*"):
                    if path.is_file():
                        add_rel(str(path.relative_to(run_dir)).replace("\\", "/"))

            deduped = list(dict.fromkeys(rels))
            run["artifacts"] = [artifact_record(run["id"], run_dir, rel) for rel in deduped if (run_dir / rel).exists()]
            run["updated_at"] = utc_now()

        run = await self.update_run(run_id, apply)
        if run:
            await self.bus.publish(run_id, {"type": "run", "run": run})
