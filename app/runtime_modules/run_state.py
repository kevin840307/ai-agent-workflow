from __future__ import annotations

from pathlib import Path
import hashlib
import mimetypes
import re
from typing import Any

from app.workflow_runtime.failure_diagnosis import diagnose_agent_failure, summarize_failure_diagnosis
from app.workflow_runtime.failure_classifier import classify_failure
from app.workflow_runtime.repair_policy import policy_for_failure, render_repair_prompt, write_repair_policy_artifact
from app.core.paths import read_text, utc_now, write_text
from app.workflow_runtime.event_log import append_event as append_workflow_event
from app.workflow_runtime.artifact_policy import artifact_display_metadata, artifact_preview_kind, enrich_artifact_records
from app.stores import FileArtifactStore, FileEventStore, FileRunStore, FileStepStore

MAX_RUN_LOG_CHARS = 250_000
ARTIFACT_METADATA_SCHEMA = "aiwf.artifact-metadata.v2"


CORE_ARTIFACT_METADATA: dict[str, dict[str, Any]] = {
    "requirement.md": {"category": "report", "role": "requirement", "display_name": "原始需求", "display_order": 5, "visibility": "supporting"},
    "input/questions.md": {"category": "report", "role": "questions", "display_name": "待確認問題", "display_order": 210, "visibility": "supporting"},
    "input/answers.md": {"category": "report", "role": "answers", "display_name": "使用者回答", "display_order": 220, "visibility": "supporting"},
    "input/guidance.md": {"category": "report", "role": "guidance", "display_name": "人工指引", "display_order": 230, "visibility": "supporting"},
    "input/failure-feedback.md": {"category": "debug", "role": "failure-feedback", "display_name": "失敗回饋", "display_order": 420, "visibility": "diagnostic"},
    "prompts/skill-context.md": {"category": "prompt", "role": "prompt", "display_name": "Skill Context", "display_order": 390, "visibility": "diagnostic"},
    ".workflow/run-log.md": {"category": "console", "role": "log"},
    ".workflow/run-console.json": {"category": "console", "role": "timeline"},
    ".workflow/debug-bundle.json": {"category": "metadata", "role": "debug-bundle"},
    ".workflow/final-report.md": {"category": "report", "role": "final-report"},
    ".workflow/version-metadata.json": {"category": "metadata", "role": "version"},
    ".workflow/project-snapshot-before.json": {"category": "metadata", "role": "state", "display_name": "專案基線快照", "display_order": 335, "visibility": "diagnostic"},
    ".workflow/patch-review-feedback.json": {"category": "patch", "role": "review-feedback"},
    ".workflow/patch-review-feedback.md": {"category": "patch", "role": "review-feedback"},
    ".workflow/run-summary.md": {"category": "report", "role": "summary"},
    ".workflow/run-trace.json": {"category": "report", "role": "trace"},
    ".workflow/gate-report.md": {"category": "report", "role": "gate"},
    ".workflow/gate-report.json": {"category": "report", "role": "gate"},
    ".workflow/run-diff.md": {"category": "diff", "role": "run-diff"},
    ".workflow/run-diff.json": {"category": "diff", "role": "run-diff"},
    ".workflow/state.json": {"category": "metadata", "role": "state"},
    ".workflow/events.jsonl": {"category": "metadata", "role": "events"},
    ".workflow/patch-approval.json": {"category": "patch", "role": "approval"},
    ".workflow/patch-approval.md": {"category": "patch", "role": "approval"},
    ".workflow/patch-apply-result.json": {"category": "patch", "role": "apply-result", "display_name": "Patch 套用結果", "display_order": 160, "visibility": "supporting"},
    ".workflow/artifacts/reports/final-report.md": {"category": "report", "role": "final-report"},
    ".workflow/artifacts/reports/run-summary.md": {"category": "report", "role": "summary"},
    ".workflow/artifacts/reports/gate-report.md": {"category": "report", "role": "gate"},
    ".workflow/artifacts/reports/gate-report.json": {"category": "report", "role": "gate"},
    ".workflow/artifacts/reports/final-review.md": {"category": "report", "role": "final-review"},
    ".workflow/artifacts/reports/verifier-report.json": {"category": "report", "role": "verifier"},
    ".workflow/artifacts/reports/run-trace.json": {"category": "report", "role": "trace"},
    ".workflow/artifacts/reports/agent-safety-report.md": {"category": "report", "role": "summary", "display_name": "Agent 安全報告", "display_order": 95, "visibility": "essential"},
    ".workflow/artifacts/reports/agent-safety-report.json": {"category": "report", "role": "summary", "display_name": "Agent 安全證據", "display_order": 96, "visibility": "essential"},
    ".workflow/artifacts/diff/run-diff.md": {"category": "diff", "role": "run-diff"},
    ".workflow/artifacts/diff/run-diff.json": {"category": "diff", "role": "run-diff"},
    ".workflow/artifacts/validation/test-result.md": {"category": "validation", "role": "test"},
    ".workflow/artifacts/validation/external-validation-result.md": {"category": "validation", "role": "external-validation"},
    ".workflow/artifacts/metadata/debug-bundle.json": {"category": "metadata", "role": "debug-bundle"},
    ".workflow/artifacts/metadata/state.json": {"category": "metadata", "role": "state"},
    ".workflow/artifacts/metadata/events.jsonl": {"category": "metadata", "role": "events"},
    ".workflow/artifacts/metadata/version-metadata.json": {"category": "metadata", "role": "version"},
    ".workflow/artifacts/index.json": {"category": "metadata", "role": "artifact-index", "display_name": "Artifact Index", "display_order": 370, "visibility": "diagnostic"},
}


def _artifact_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _normalize_artifact_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.startswith(("output/", "input/", "prompts/", ".workflow/")):
        return raw
    return f"output/{raw}"


def _contract_values(value: Any) -> list[Any]:
    """Normalize structural config values without interpreting their text."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _explicit_artifact_contracts(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = config.get("artifactContracts", config.get("artifact_contracts"))
    rows: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        iterable = []
        for path, metadata in raw.items():
            item = dict(metadata) if isinstance(metadata, dict) else {}
            item.setdefault("path", path)
            iterable.append(item)
    elif isinstance(raw, list):
        iterable = [dict(item) for item in raw if isinstance(item, dict)]
    else:
        iterable = []
    for item in iterable:
        normalized = _normalize_artifact_path(item.get("path") or item.get("file") or item.get("output"))
        if normalized:
            rows[normalized] = item
    return rows


def _step_artifact_metadata(run: dict[str, Any], rel_path: str) -> dict[str, Any] | None:
    """Resolve artifact metadata from explicit step/output contracts.

    Declared ``outputs`` are structural contracts, not filename semantics.  A
    custom workflow may optionally attach per-file ``artifactContracts``.  When
    it does not, the artifact is still classified as a generic Step/Validation
    output instead of being shown as unclassified.
    """
    normalized = str(rel_path or "").replace("\\", "/")
    for step in run.get("steps") or []:
        key = str(step.get("key") or "").strip()
        config = step.get("config") or {}
        prompt_paths = {
            f"prompts/{key}.md",
            f"prompts/{key}.effective.md",
            f"prompts/{key}.prompt-meta.json",
        } if key else set()
        if normalized in prompt_paths:
            defaults = artifact_display_metadata(category="prompt", role="prompt")
            return {
                **defaults,
                "display_name": f"{step.get('title') or key} · Agent Prompt",
                "producer_step_key": key or None,
            }

        explicit_contract = _explicit_artifact_contracts(config).get(normalized)
        output_values = [
            *_contract_values(config.get("outputs")),
            *_contract_values(config.get("expectedFiles")),
            config.get("outputFile"),
            config.get("filename"),
        ]
        output_paths = {_normalize_artifact_path(value) for value in output_values if value}
        if normalized not in output_paths and explicit_contract is None:
            continue

        contract = explicit_contract or {}
        evidence_category = str(config.get("evidenceCategory") or config.get("evidence_category") or "").strip()
        category = str(
            contract.get("category")
            or contract.get("artifactCategory")
            or config.get("artifactCategory")
            or config.get("artifact_category")
            or ("validation" if evidence_category == "validation" else "step")
        )
        role = str(
            contract.get("role")
            or contract.get("artifactRole")
            or config.get("artifactRole")
            or config.get("artifact_role")
            or ("validation-output" if category == "validation" else "step-output")
        )
        defaults = artifact_display_metadata(category=category, role=role)
        file_label = Path(normalized).name
        display_name = str(
            contract.get("displayName")
            or contract.get("display_name")
            or contract.get("artifactDisplayName")
            or config.get("artifactDisplayName")
            or config.get("artifact_display_name")
            or f"{step.get('title') or key} · {file_label}"
        )
        return {
            "category": category,
            "role": role,
            "display_name": display_name,
            "display_order": int(
                contract.get("displayOrder")
                or contract.get("display_order")
                or config.get("artifactDisplayOrder")
                or config.get("artifact_display_order")
                or defaults["display_order"]
            ),
            "visibility": str(
                contract.get("visibility")
                or contract.get("artifactVisibility")
                or config.get("artifactVisibility")
                or config.get("artifact_visibility")
                or defaults["visibility"]
            ),
            "producer_step_key": key or None,
        }
    return None


def artifact_record(run_or_id: dict[str, Any] | str, run_dir: Path, rel_path: str) -> dict[str, Any]:
    run = run_or_id if isinstance(run_or_id, dict) else {"id": run_or_id, "steps": []}
    run_id = str(run.get("id") or run_or_id)
    path = run_dir / rel_path
    normalized = str(rel_path or "").replace("\\", "/")
    contracts = run.get("artifact_contracts") if isinstance(run.get("artifact_contracts"), dict) else {}
    contract = contracts.get(normalized) if isinstance(contracts.get(normalized), dict) else None
    explicit = dict(CORE_ARTIFACT_METADATA.get(normalized) or contract or _step_artifact_metadata(run, normalized) or {
        "category": "unclassified",
        "role": "unclassified",
        "display_name": "未分類產物",
        "display_order": 900,
        "visibility": "supporting",
        "producer_step_key": None,
    })
    defaults = artifact_display_metadata(category=explicit.get("category"), role=explicit.get("role"))
    media_type, _encoding = mimetypes.guess_type(path.name)
    resolved_media_type = media_type or "text/plain"
    return {
        "id": f"{run_id}:{normalized.replace('/', '|')}",
        "run_id": run_id,
        "name": Path(normalized).name,
        "path": normalized,
        "size": path.stat().st_size if path.exists() else 0,
        "content_hash": _artifact_hash(path),
        "category": explicit.get("category") or defaults["category"],
        "role": explicit.get("role") or defaults["role"],
        "display_name": explicit.get("display_name") or defaults["display_name"],
        "display_order": int(explicit.get("display_order", defaults["display_order"])),
        "visibility": explicit.get("visibility") or defaults["visibility"],
        "producer_step_key": explicit.get("producer_step_key"),
        "media_type": resolved_media_type,
        "preview_kind": artifact_preview_kind(media_type=resolved_media_type, role=explicit.get("role") or defaults["role"]),
        "metadata_schema": ARTIFACT_METADATA_SCHEMA,
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


def stop_condition_for_failure(error_class: str) -> str:
    return {
        "PATH_VIOLATION": "All changed paths are inside Project Path and the project guard passes.",
        "TIMEOUT": "The target step completes within its timeout and produces verifiable output.",
        "NO_FILE_OUTPUT": "The owner step creates or modifies the required project files and the filesystem diff is non-empty.",
        "NO_TEST_GENERATED": "At least one canonical test file exists under tests/ and can be collected.",
        "NO_PRODUCTION_CHANGE": "The intended production files are changed and pass the step acceptance checks.",
        "SYNTAX_ERROR": "The affected source and tests compile/import without syntax errors.",
        "TEST_FAILED": "The configured deterministic test command exits with code 0.",
        "VALIDATION_FAILED": "The configured validation script exits with code 0.",
        "AGENT_OUTPUT_FORMAT": "The step returns the required valid artifact or filesystem result without format errors.",
    }.get(error_class, "The failed acceptance gate passes with concrete evidence and no unresolved error remains.")


def repair_strategy_for_class(error_class: str) -> str:
    return {
        "PATH_VIOLATION": "Use only project-relative paths inside Project Path; do not retry unsafe path tricks.",
        "TIMEOUT": "Reduce scope, simplify implementation, and avoid long-running commands.",
        "NO_FILE_OUTPUT": "Use Qwen/OpenCode direct edits for the owner step. Completion is verified from actual project diffs.",
        "NO_TEST_GENERATED": "Create focused test files directly under tests/.",
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
            "Build did not produce acceptable production changes.",
            "Use Qwen/OpenCode direct edits inside the selected Project Path and leave a verifiable project diff.",
        ])
    else:
        notes.append("Retry the target step using the concrete error message and previously approved artifacts as the source of truth.")

    if "outside project path" in text or "unsafe file path" in text or "parent directory" in text:
        notes.append("Workspace isolation was enforced: writes must stay inside the selected Project Path; external paths are read-only context.")
    if "validation scripts" in text:
        notes.append("Existing validation scripts are protected acceptance tools and must not be overwritten by Build.")
    if "test files" in text:
        notes.append("Build owns production files only; Generate Tests owns tests/ files only.")
    return notes


class RunState:
    def __init__(self, store, bus) -> None:
        self.store = store
        self.bus = bus
        self._store_facade_source = None
        self._sync_store_facades()

    def _sync_store_facades(self) -> None:
        # Tests and CLI instances may swap `runtime.store` / `run_state.store` at
        # runtime.  Keep Store facades bound to the current backend so state
        # transitions do not accidentally write to a stale JSON/SQLite backend.
        if self._store_facade_source is self.store:
            return
        self.run_store = FileRunStore(read=self.store.read, mutate=self.store.mutate)
        self.step_store = FileStepStore(self.run_store)
        self.artifact_store = FileArtifactStore(self.run_store)
        self.event_store = FileEventStore(self.run_store)
        self._store_facade_source = self.store

    async def update_run(self, run_id: str, fn) -> dict[str, Any] | None:
        self._sync_store_facades()
        return await self.run_store.mutate_run(run_id, fn)

    async def get_run_record(self, run_id: str) -> dict[str, Any]:
        from fastapi import HTTPException

        self._sync_store_facades()
        run = await self.run_store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    async def transition_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        error_code: str | None = None,
        ended: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        self._sync_store_facades()
        run = await self.run_store.transition_status(
            run_id,
            status,
            error=error,
            error_code=error_code,
            ended=ended,
            extra=extra,
        )
        if run:
            await self.event_store.append(run_id, {"type": f"run.{status}", "status": status, "message": error or f"run {status}", "error_code": error_code})
            await self.bus.publish(run_id, {"type": "run", "run": run})
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
        try:
            append_workflow_event(run, "run.log", message=message)
        except Exception:
            pass
        await self.bus.publish(run["id"], {"type": "log", "message": line})

    async def set_step(
        self,
        run_id: str,
        key: str,
        status: str,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._sync_store_facades()
        run = await self.step_store.mark(run_id, key, status, error=error, error_code=error_code)
        if run:
            try:
                append_workflow_event(run, f"step.{status}", step_key=key, message=error or f"{key}: {status}", status=status, error_code=error_code)
            except Exception:
                pass
            await self.bus.publish(run_id, {"type": "run", "run": run})

    async def reset_steps_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        self._sync_store_facades()
        run = await self.step_store.reset_from(run_id, start_index)
        if run:
            await self.event_store.append(run_id, {"type": "steps.reset", "start_index": start_index, "message": f"steps reset from {start_index}"})
            await self.bus.publish(run_id, {"type": "run", "run": run})
        return run

    async def reset_retry_counts_from(self, run_id: str, start_index: int) -> dict[str, Any] | None:
        self._sync_store_facades()
        run = await self.step_store.reset_retry_counts_from(run_id, start_index)
        if run:
            await self.event_store.append(run_id, {"type": "retry.reset", "start_index": start_index, "message": f"retry counts reset from {start_index}"})
            await self.bus.publish(run_id, {"type": "run", "run": run})
        return run

    async def get_step_retry_count(self, run_id: str, key: str) -> int:
        self._sync_store_facades()
        step = await self.step_store.get(run_id, key)
        return int((step or {}).get("retry_count", 0) or 0)

    async def increment_step_retry(self, run_id: str, key: str) -> int:
        self._sync_store_facades()
        run, result = await self.step_store.increment_retry(run_id, key)
        if run:
            await self.event_store.append(run_id, {"type": "retry.incremented", "step_key": key, "retry_count": result, "message": f"{key} retry {result}"})
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
        raw_error = str(exc).strip()
        error = raw_error[:2000]
        notes = retry_recovery_notes(source_key, target_key, error)[:4]
        failure = classify_failure(error, step_key=source_key)
        repair_policy = policy_for_failure(error, step_key=source_key, retry_count=retry_count)
        write_repair_policy_artifact(run, target_key, error, retry_count=retry_count)
        entry = (
            f"## Retry Feedback for {target_key}\n\n"
            f"Submitted at: {utc_now()}\n\n"
            f"- Failed step: {source_key}\n"
            f"- Retry target: {target_key}\n"
            f"- Retry attempt: {retry_count}/{max_retries}\n"
            f"- Failure classifier: {failure.get('code')}\n"
            f"- Agent diagnosis: {summarize_failure_diagnosis(error, step_key=source_key)[:500]}\n\n"
            "### Recovery analysis\n"
            + "".join(f"- {note[:300]}\n" for note in notes)
            + f"- Stop condition: {stop_condition_for_failure(classify_repair_error(source_key, target_key, error))}\n"
            + "\n### Error message to fix\n\n"
            f"{error}\n\n"
        )
        # Keep only the latest three compact records. Full transcripts remain in
        # run-log/events; retry prompts must not grow with repeated source code.
        blocks = re.findall(r"^## Retry Feedback for .*?(?=^## Retry Feedback for |\Z)", previous, flags=re.MULTILINE | re.DOTALL)
        compact = "\n".join((blocks[-2:] + [entry]))
        write_text(feedback_path, compact.rstrip() + "\n")
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
                "failure_class": classify_failure(error, step_key=source_key),
                "agent_diagnosis": diagnose_agent_failure(error, step_key=source_key),
                "repair_policy": repair_policy,
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
        self._sync_store_facades()
        run = await self.step_store.append_event(run_id, step_key, event)
        if run:
            try:
                append_workflow_event(run, kind, step_key=step_key, message=message, extra=extra)
            except Exception:
                pass
            await self.event_store.append(run_id, {"type": kind, "step_key": step_key, "message": message, **(extra or {})})
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
                ".workflow/gate-report.md",
                ".workflow/gate-report.json",
                ".workflow/run-diff.md",
                ".workflow/run-diff.json",
                ".workflow/project-snapshot-before.json",
                ".workflow/state.json",
                ".workflow/events.jsonl",
                ".workflow/artifacts/index.json",
                ".workflow/artifacts/README.md",
                ".workflow/artifacts/reports/agent-safety-report.md",
                ".workflow/artifacts/reports/agent-safety-report.json",
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
                add_rel(f"prompts/{step.get('key')}.effective.md")
                add_rel(f"prompts/{step.get('key')}.prompt-meta.json")
                add_rel(config.get("outputFile") or config.get("filename"))
                for expected in _contract_values(config.get("expectedFiles")):
                    add_rel(expected)
                for output in _contract_values(config.get("outputs")):
                    add_rel(output)
                for artifact in [
                    *_contract_values(config.get("contextArtifacts")),
                    *_contract_values(config.get("dependsOnArtifacts")),
                ]:
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
            run["_artifact_refresh_candidates"] = [artifact_record(run, run_dir, rel) for rel in deduped if (run_dir / rel).exists()]
            run["artifact_metadata_schema"] = ARTIFACT_METADATA_SCHEMA

        run = await self.update_run(run_id, apply)
        if run:
            artifacts = enrich_artifact_records(list(run.pop("_artifact_refresh_candidates", [])))
            self._sync_store_facades()
            run = await self.artifact_store.replace_for_run(run_id, artifacts) or run
            await self.bus.publish(run_id, {"type": "run", "run": run})
