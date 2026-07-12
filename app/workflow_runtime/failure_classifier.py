from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FailureClass:
    code: str
    title: str
    description: str
    retry_target: str
    repair_prompt_hint: str
    severity: str = "medium"
    auto_repairable: bool = False
    retryable: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        user_message, recommended_action = _USER_MESSAGES.get(self.code, (self.description, self.repair_prompt_hint))
        return {
            "code": self.code,
            "title": self.title,
            "description": self.description,
            "retry_target": self.retry_target,
            "repair_prompt_hint": self.repair_prompt_hint,
            "severity": self.severity,
            "user_message": user_message,
            "auto_repairable": self.auto_repairable,
            "retryable": self.auto_repairable if self.retryable is None else self.retryable,
            "recommended_action": recommended_action,
        }


_USER_MESSAGES = {
    "NO_FILE_CHANGE": ("未偵測到專案檔案變更。", "請讓 Agent 直接在 Project Path 建立或修改必要檔案。"),
    "VALIDATION_FAILED": ("專案驗證未通過。", "依照 validation 的輸出修正程式，再重新驗證。"),
    "VALIDATION_FILE_NOT_FOUND": ("必要驗證檔不存在。", "恢復或指定原始驗證檔後再執行；不可跳過 required validation。"),
    "VALIDATION_FILE_MUTATED": ("必要驗證檔在執行期間被修改。", "還原原始驗證檔並用新的 Agent Session 重試。"),
    "VALIDATION_NOT_EXECUTED": ("必要驗證尚未真正執行成功。", "執行相同驗證命令並取得 Exit Code 0 後才能完成。"),
    "TEST_LAYOUT_CONFLICT": ("測試檔版面衝突，根目錄與 tests/ 可能有同名測試。", "系統會優先安全清理本次 Run 產生的重複測試後重跑。"),
    "TEST_DEFINITION_INVALID": ("產生的測試定義無法被 pytest 正確收集。", "只重新產生測試；不要重做 production code。"),
    "TEST_FAILED": ("自動化測試未通過。", "依失敗案例修正 production code，除非測試本身明確錯誤。"),
    "REVIEW_FAILED": ("品質檢查發現尚未符合的需求。", "依 Review 缺漏項目做最小範圍修正。"),
    "CONTEXT_LIMIT_REACHED": ("Agent Session 的上下文已滿。", "使用精簡 handoff 建立新 Session，從目前步驟繼續。"),
    "AGENT_SESSION_RECOVERABLE": ("Agent Session 已失效或衝突。", "建立新 Session 並使用精簡 handoff 從目前步驟繼續。"),
    "TIMEOUT": ("目前步驟執行逾時。", "保留有效變更並用新 Session 重試，或縮小單次任務範圍。"),
    "INVALID_OUTPUT": ("Agent 回傳格式無法使用。", "請 Agent 直接使用檔案工具修改專案，並回傳要求的結構化結果。"),
    "PROJECT_GUARD_BLOCKED": ("系統阻擋了 Project Path 以外的寫入。", "只使用 Project Path 內的相對路徑。"),
    "EXPECTED_FILES_MISSING": ("步驟要求的輸出檔案尚未產生。", "建立 Step Contract 指定的檔案後再繼續。"),
    "AGENT_EMPTY_OUTPUT": ("Agent 沒有回傳可用結果。", "檢查 Agent 設定，並以更短、更直接的指令重試。"),
    "AGENT_PROCESS_FAILED": ("Agent CLI 執行失敗。", "檢查 stderr、模型連線與 CLI 設定後再重試。"),
    "AGENT_CLI_NOT_FOUND": ("找不到指定的 Agent CLI。", "完成 Setup Smoke，確認 CLI 路徑與 PATH 後再執行。"),
    "WORKFLOW_CONFIG_INVALID": ("Workflow 設定不合法。", "修正 Workflow Asset／設定檔後重新驗證。"),
    "RETRY_LOOP_DETECTED": ("系統偵測到沒有進展的重試迴圈。", "查看最後一次失敗證據，縮小任務或調整驗證條件後再執行。"),
    "USER_INPUT_REQUIRED": ("Workflow 需要使用者補充資訊。", "回答畫面上的必要問題後繼續。"),
    "WORKFLOW_CANCELLED": ("Workflow 已取消。", "需要時可從安全 Checkpoint 重新執行。"),
    "UNKNOWN": ("系統尚未辨識這個錯誤類型。", "開啟技術診斷查看原始紀錄。"),
}

_FAILURES: dict[str, FailureClass] = {
    "NO_FILE_CHANGE": FailureClass(
        "NO_FILE_CHANGE", "Agent did not change project files",
        "The workflow expected real project edits, but no changed files were detected under Project Path.",
        "implementation step", "Directly create or modify the required files in the selected project. Do not only explain the plan.",
        "high", True,
    ),
    "VALIDATION_FAILED": FailureClass(
        "VALIDATION_FAILED", "Validation script failed",
        "The user/project validation script exited non-zero or reported an assertion failure.",
        "implementation step", "Use validation stdout/stderr as the acceptance oracle and repair production files until validation exits 0.",
        "high", True,
    ),
    "VALIDATION_FILE_NOT_FOUND": FailureClass(
        "VALIDATION_FILE_NOT_FOUND", "Required validation file is missing",
        "A required validation contract points to a file that does not exist.",
        "blocked", "Restore or configure the original validation file; do not bypass it.", "high", False, False,
    ),
    "VALIDATION_FILE_MUTATED": FailureClass(
        "VALIDATION_FILE_MUTATED", "Protected validation file changed",
        "The immutable user validation file hash changed during the run.",
        "implementation step with fresh session", "Restore the original validation file and repair production code only.",
        "critical", False, False,
    ),
    "VALIDATION_NOT_EXECUTED": FailureClass(
        "VALIDATION_NOT_EXECUTED", "Required validation did not execute",
        "Required validation has no successful exit-code evidence.",
        "validation step", "Run the same protected validation contract again after repair until it exits 0.",
        "high", False, False,
    ),
    "TEST_DEFINITION_INVALID": FailureClass(
        "TEST_DEFINITION_INVALID", "Generated test definition is invalid",
        "Generated pytest tests contain unresolved fixture arguments or invalid collection definitions.",
        "generate_tests", "Regenerate only invalid tests and preserve accepted production checkpoints.", "high", True,
    ),
    "TEST_LAYOUT_CONFLICT": FailureClass(
        "TEST_LAYOUT_CONFLICT", "Pytest layout conflict",
        "Pytest found conflicting test modules, commonly a root test_*.py and tests/ counterpart.",
        "deterministic test-layout repair", "Remove only current-run duplicate root tests, clear pytest caches, and rerun tests.",
        "high", True,
    ),
    "TEST_FAILED": FailureClass(
        "TEST_FAILED", "Automated tests failed", "The configured test command or pytest/unittest step failed.",
        "implementation step", "Repair production code first using failing assertions. Change tests only when clearly invalid.",
        "high", True,
    ),
    "REVIEW_FAILED": FailureClass(
        "REVIEW_FAILED", "Review gate failed",
        "The review step found missing requirements, unsafe changes, or incomplete evidence.",
        "implementation step", "Produce a minimal repair that satisfies the missing acceptance criteria.", "medium", True,
    ),
    "CONTEXT_LIMIT_REACHED": FailureClass(
        "CONTEXT_LIMIT_REACHED", "Agent context limit reached",
        "The resumed agent session could not fit more history, even after its own compression attempt.",
        "same step with fresh session handoff", "Create a compact handoff and continue in a fresh session.", "high", True,
    ),
    "AGENT_SESSION_RECOVERABLE": FailureClass(
        "AGENT_SESSION_RECOVERABLE", "Agent session is recoverable",
        "The previous agent session is missing, conflicting, archived, or already in use.",
        "same step with fresh session handoff", "Create a fresh session and continue with a compact handoff.", "medium", True,
    ),
    "TIMEOUT": FailureClass(
        "TIMEOUT", "Step timed out", "An agent, test, or validation process exceeded its timeout.",
        "same step or smaller replanned task", "Reduce task scope, use a fresh session, or adjust the step timeout.", "medium", True,
    ),
    "INVALID_OUTPUT": FailureClass(
        "INVALID_OUTPUT", "Invalid agent output",
        "The agent returned malformed JSON, tool-call JSON, FILE blocks in real mode, or unusable output.",
        "same step", "Use the CLI file editing capability directly and return valid artifact text.", "medium", True,
    ),
    "PROJECT_GUARD_BLOCKED": FailureClass(
        "PROJECT_GUARD_BLOCKED", "Project guard blocked a write",
        "The workflow rejected an unsafe path or a write outside the selected project.",
        "same step", "Use relative paths inside Project Path only. External folders are read-only context.", "high", True,
    ),
    "EXPECTED_FILES_MISSING": FailureClass(
        "EXPECTED_FILES_MISSING", "Expected files are missing",
        "The step contract declared output files that were not produced.",
        "producer step", "Create the exact expected file paths from the step contract before continuing.", "medium", True,
    ),
    "AGENT_EMPTY_OUTPUT": FailureClass(
        "AGENT_EMPTY_OUTPUT", "Agent returned empty output",
        "The CLI process returned no usable stdout and no detected project changes.",
        "same step", "Retry with a shorter direct instruction and verify agent configuration.", "medium", True,
    ),
    "AGENT_PROCESS_FAILED": FailureClass(
        "AGENT_PROCESS_FAILED", "Agent process failed",
        "The CLI process exited with a non-zero code before producing acceptable results.",
        "same step", "Inspect stderr/stdout and retry after fixing configuration or prompt scope.", "high", True,
    ),
    "AGENT_CLI_NOT_FOUND": FailureClass(
        "AGENT_CLI_NOT_FOUND", "Agent CLI not found", "The configured Qwen/OpenCode executable could not be started.",
        "blocked", "Configure the CLI executable or PATH and rerun Setup Smoke.", "high", False, False,
    ),
    "WORKFLOW_CONFIG_INVALID": FailureClass(
        "WORKFLOW_CONFIG_INVALID", "Workflow configuration is invalid",
        "A workflow, step contract, metadata file, or runtime setting failed deterministic validation.",
        "blocked", "Fix the configuration and rerun the workflow asset validator.", "high", False, False,
    ),
    "RETRY_LOOP_DETECTED": FailureClass(
        "RETRY_LOOP_DETECTED", "Retry loop detected",
        "The same failure repeated without measurable project or validation progress.",
        "manual inspection or smaller replan", "Inspect evidence and change task scope or validation before retrying.", "high", False, False,
    ),
    "USER_INPUT_REQUIRED": FailureClass(
        "USER_INPUT_REQUIRED", "User input is required", "The workflow cannot continue without a required user answer.",
        "waiting_input", "Provide the required answer and resume from the current checkpoint.", "low", False, False,
    ),
    "WORKFLOW_CANCELLED": FailureClass(
        "WORKFLOW_CANCELLED", "Workflow cancelled", "The run was cancelled by the user or controller shutdown path.",
        "cancelled", "Restart from a safe checkpoint if the work is still required.", "low", False, False,
    ),
    "UNKNOWN": FailureClass(
        "UNKNOWN", "Unclassified failure", "The platform could not map this error to a known workflow failure class.",
        "manual inspection", "Inspect run-log.md, prompts, artifacts, and validation evidence before retrying.", "medium", False, False,
    ),
}

_CODE_ALIASES = {
    "PROJECT_DIFF_MISSING": "NO_FILE_CHANGE",
    "NO_PROJECT_CHANGES": "NO_FILE_CHANGE",
    "AGENT_TIMEOUT": "TIMEOUT",
    "AGENT_OUTPUT_FORMAT": "INVALID_OUTPUT",
    "EXPECTED_FILES_MISSING": "EXPECTED_FILES_MISSING",
    "AGENT_OUTPUT_EMPTY": "AGENT_EMPTY_OUTPUT",
    "AGENT_PROCESS_FAILED": "AGENT_PROCESS_FAILED",
    "AGENT_SESSION_RECOVERABLE": "AGENT_SESSION_RECOVERABLE",
    "CONTEXT_LIMIT_REACHED": "CONTEXT_LIMIT_REACHED",
    "AGENT_CLI_NOT_FOUND": "AGENT_CLI_NOT_FOUND",
    "WORKFLOW_CONFIG_INVALID": "WORKFLOW_CONFIG_INVALID",
    "WORKFLOW_CANCELLED": "WORKFLOW_CANCELLED",
    "USER_INPUT_REQUIRED": "USER_INPUT_REQUIRED",
    "RETRY_LOOP_DETECTED": "RETRY_LOOP_DETECTED",
}


def canonical_failure_code(value: Any) -> str | None:
    code = str(value or "").strip().upper().replace("-", "_")
    if not code:
        return None
    code = _CODE_ALIASES.get(code, code)
    return code if code in _FAILURES else None


def _structured_payload(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        nested = value.get("failure")
        return nested if isinstance(nested, Mapping) else value
    if isinstance(value, BaseException):
        payload: dict[str, Any] = {}
        for attr in ("failure_code", "error_code", "code"):
            attr_value = getattr(value, attr, None)
            if attr_value:
                payload[attr] = attr_value
        if payload:
            payload["message"] = str(value)
            return payload
        return None
    text = str(value or "").strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _message_text(value: Any, payload: Mapping[str, Any] | None) -> str:
    if payload:
        for key in ("summary", "message", "error", "detail", "raw_message"):
            if payload.get(key):
                return str(payload[key])
    return str(value or "")


def _result(code: str, *, source: str, step_key: str | None = None) -> dict[str, Any]:
    result = _FAILURES[code].as_dict()
    result["classification_source"] = source
    if step_key:
        result["step_key"] = step_key
    return result


def classify_failure(message: Any = None, *, step_key: str | None = None, error_code: str | None = None) -> dict[str, Any]:
    """Return one canonical failure class for retry, UI, reports, and tests.

    Deterministic error codes always win. Text matching is retained only as a
    compatibility adapter for third-party CLI output that has no structured
    error contract yet.
    """
    payload = _structured_payload(message)
    explicit_candidates = [error_code]
    if payload:
        explicit_candidates.extend(payload.get(key) for key in ("code", "error_code", "failure_code"))
    if isinstance(message, BaseException):
        explicit_candidates.extend(getattr(message, key, None) for key in ("failure_code", "error_code", "code"))
    for candidate in explicit_candidates:
        code = canonical_failure_code(candidate)
        if code:
            return _result(code, source="error_code" if candidate == error_code else "structured", step_key=step_key)

    lower = _message_text(message, payload).lower()
    if any(marker in lower for marker in ["outside project", "project guard", "unsafe file path", "parent-directory", "absolute path"]):
        return _result("PROJECT_GUARD_BLOCKED", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["no files changed", "project changes were required", "did not directly create or modify", "did not create or modify"]):
        return _result("NO_FILE_CHANGE", source="text_fallback", step_key=step_key)
    if "validation_file_not_found" in lower:
        return _result("VALIDATION_FILE_NOT_FOUND", source="text_fallback", step_key=step_key)
    if "validation_file_mutated" in lower:
        return _result("VALIDATION_FILE_MUTATED", source="text_fallback", step_key=step_key)
    if "validation_not_executed" in lower or "required user validation did not pass" in lower:
        return _result("VALIDATION_NOT_EXECUTED", source="text_fallback", step_key=step_key)
    if "validation" in lower and any(marker in lower for marker in ["failed", "assertion", "non-zero", "exit code", "error"]):
        return _result("VALIDATION_FAILED", source="text_fallback", step_key=step_key)
    if "unresolved required fixture arguments" in lower or "test_definition_invalid" in lower:
        return _result("TEST_DEFINITION_INVALID", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["test_layout_conflict", "import file mismatch", "is not the same as the test file"]):
        return _result("TEST_LAYOUT_CONFLICT", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["pytest", "unittest", "test_command", "tests failed", "test failed", "assertionerror"]):
        return _result("TEST_FAILED", source="text_fallback", step_key=step_key)
    if "review" in lower and any(marker in lower for marker in ["fail", "failed", "risk", "missing"]):
        return _result("REVIEW_FAILED", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["context is too large", "maximum context length", "compression status: noop", "hard limit", "too many tokens"]):
        return _result("CONTEXT_LIMIT_REACHED", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["session not found", "invalid session", "session is already in use", "session id already exists", "no saved session found"]):
        return _result("AGENT_SESSION_RECOVERABLE", source="text_fallback", step_key=step_key)
    if "timed out" in lower or "timeout" in lower:
        return _result("TIMEOUT", source="text_fallback", step_key=step_key)
    if any(marker in lower for marker in ["tool-call json", "write_file", "edit_file", "file/content/end_file", "file block", "invalid json", "malformed json"]):
        return _result("INVALID_OUTPUT", source="text_fallback", step_key=step_key)
    if "expected file(s) not found" in lower or ("expected files" in lower and "missing" in lower):
        return _result("EXPECTED_FILES_MISSING", source="text_fallback", step_key=step_key)
    if "returned empty" in lower or "empty stdout" in lower:
        return _result("AGENT_EMPTY_OUTPUT", source="text_fallback", step_key=step_key)
    if "process failed with exit code" in lower:
        return _result("AGENT_PROCESS_FAILED", source="text_fallback", step_key=step_key)
    if "cli not found" in lower or "no such file or directory" in lower and "qwen" in lower:
        return _result("AGENT_CLI_NOT_FOUND", source="text_fallback", step_key=step_key)
    return _result("UNKNOWN", source="default", step_key=step_key)


def classify_step_failure(step: dict[str, Any]) -> dict[str, Any]:
    return classify_failure(step.get("failure") or step.get("error"), step_key=step.get("key"), error_code=step.get("error_code"))


def classify_run_failures(run: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in run.get("steps") or []:
        if step.get("status") in {"failed", "waiting_input", "cancelled"} or step.get("error") or step.get("failure"):
            item = classify_step_failure(step)
            item.update({"step_key": step.get("key"), "step_status": step.get("status"), "error": step.get("error")})
            steps.append(item)
    run_failure_input = run.get("failure") or run.get("error")
    run_class = classify_failure(run_failure_input, error_code=run.get("error_code")) if run_failure_input else None
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "run_failure": run_class,
        "step_failures": steps,
        "has_failures": bool(run_class or steps),
    }


__all__ = [
    "FailureClass",
    "canonical_failure_code",
    "classify_failure",
    "classify_step_failure",
    "classify_run_failures",
]
