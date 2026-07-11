from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FailureClass:
    code: str
    title: str
    description: str
    retry_target: str
    repair_prompt_hint: str
    severity: str = "medium"
    auto_repairable: bool = False

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
    "TIMEOUT": ("目前步驟執行逾時。", "保留有效變更並用新 Session 重試，或縮小單次任務範圍。"),
    "INVALID_OUTPUT": ("Agent 回傳格式無法使用。", "請 Agent 直接使用檔案工具修改專案，並回傳要求的結構化結果。"),
    "PROJECT_GUARD_BLOCKED": ("系統阻擋了 Project Path 以外的寫入。", "只使用 Project Path 內的相對路徑。"),
    "EXPECTED_FILES_MISSING": ("步驟要求的輸出檔案尚未產生。", "建立 Step Contract 指定的檔案後再繼續。"),
    "AGENT_EMPTY_OUTPUT": ("Agent 沒有回傳可用結果。", "檢查 Agent 設定，並以更短、更直接的指令重試。"),
    "AGENT_PROCESS_FAILED": ("Agent CLI 執行失敗。", "檢查 stderr、模型連線與 CLI 設定後再重試。"),
    "UNKNOWN": ("系統尚未辨識這個錯誤類型。", "開啟技術診斷查看原始紀錄。"),
}

_FAILURES: dict[str, FailureClass] = {
    "NO_FILE_CHANGE": FailureClass(
        "NO_FILE_CHANGE",
        "Agent did not change project files",
        "The workflow expected real project edits, but no changed files were detected under Project Path.",
        "implementation step",
        "Directly create or modify the required files in the selected project. Do not only explain the plan.",
        "high",
        True,
    ),
    "VALIDATION_FAILED": FailureClass(
        "VALIDATION_FAILED",
        "Validation script failed",
        "The user/project validation script exited non-zero or reported an assertion failure.",
        "implementation step",
        "Use the validation stdout/stderr as the acceptance oracle and repair production files until validation.py exits 0.",
        "high",
    ),
    "VALIDATION_FILE_NOT_FOUND": FailureClass(
        "VALIDATION_FILE_NOT_FOUND", "Required validation file is missing",
        "A required validation contract points to a file that does not exist.",
        "blocked", "Restore or configure the original validation file; do not bypass it.", "high", False,
    ),
    "VALIDATION_FILE_MUTATED": FailureClass(
        "VALIDATION_FILE_MUTATED", "Protected validation file changed",
        "The immutable user validation file hash changed during the run.",
        "implementation step with fresh session", "Restore the original validation file and repair production code only.", "critical", False,
    ),
    "VALIDATION_NOT_EXECUTED": FailureClass(
        "VALIDATION_NOT_EXECUTED", "Required validation did not execute",
        "Required validation has no successful exit-code evidence.",
        "validation step", "Run the same protected validation contract again after repair until it exits 0.", "high", False,
    ),
    "TEST_DEFINITION_INVALID": FailureClass(
        "TEST_DEFINITION_INVALID",
        "Generated test definition is invalid",
        "Generated pytest tests contain unresolved fixture arguments or invalid collection definitions.",
        "generate_tests",
        "Regenerate only the invalid tests. Preserve production code and accepted task checkpoints.",
        "high",
        True,
    ),
    "TEST_LAYOUT_CONFLICT": FailureClass(
        "TEST_LAYOUT_CONFLICT",
        "Pytest layout conflict",
        "Pytest found conflicting test modules, commonly a root test_*.py and tests/ counterpart.",
        "deterministic test-layout repair",
        "Remove only current-run duplicate root tests, clear pytest caches, and rerun tests without changing production code.",
        "high",
        True,
    ),
    "TEST_FAILED": FailureClass(
        "TEST_FAILED",
        "Automated tests failed",
        "The configured test command or pytest/unittest step failed.",
        "implementation step",
        "Repair production code first using the failing assertions. Change tests only when they are clearly invalid.",
        "high",
    ),
    "REVIEW_FAILED": FailureClass(
        "REVIEW_FAILED",
        "Review gate failed",
        "The review step found missing requirements, unsafe changes, or incomplete evidence.",
        "implementation step",
        "Read the review findings and produce a minimal repair that satisfies the missing acceptance criteria.",
    ),
    "CONTEXT_LIMIT_REACHED": FailureClass(
        "CONTEXT_LIMIT_REACHED",
        "Agent context limit reached",
        "The resumed agent session could not fit more history, even after its own compression attempt.",
        "same step with fresh session handoff",
        "Create a compact handoff with requirement, current files, completed work, validation evidence, and the latest error; then continue in a fresh session.",
        "high",
    ),
    "TIMEOUT": FailureClass(
        "TIMEOUT",
        "Step timed out",
        "An agent, test, or validation process exceeded its timeout.",
        "same step or smaller replanned task",
        "Reduce the task scope, avoid long-running commands, or increase the timeout for this step.",
    ),
    "INVALID_OUTPUT": FailureClass(
        "INVALID_OUTPUT",
        "Invalid agent output",
        "The agent returned malformed JSON, tool-call JSON, FILE blocks in real mode, or unusable output.",
        "same step",
        "Return valid artifact text or use the CLI file editing capability directly. Do not print tool-call JSON.",
    ),
    "PROJECT_GUARD_BLOCKED": FailureClass(
        "PROJECT_GUARD_BLOCKED",
        "Project guard blocked a write",
        "The workflow rejected an unsafe path or a write outside the selected project.",
        "same step",
        "Use relative paths inside Project Path only. External folders are read-only context.",
        "high",
    ),
    "EXPECTED_FILES_MISSING": FailureClass(
        "EXPECTED_FILES_MISSING",
        "Expected files are missing",
        "The step contract declared output files that were not produced.",
        "producer step",
        "Create the exact expected file paths from the step contract before continuing.",
        "medium",
        True,
    ),
    "AGENT_EMPTY_OUTPUT": FailureClass(
        "AGENT_EMPTY_OUTPUT",
        "Agent returned empty output",
        "The CLI process returned no usable stdout and no detected project changes.",
        "same step",
        "Retry with a shorter direct instruction and verify the agent command is configured correctly.",
    ),
    "AGENT_PROCESS_FAILED": FailureClass(
        "AGENT_PROCESS_FAILED",
        "Agent process failed",
        "The CLI process exited with a non-zero code before producing acceptable results.",
        "same step",
        "Inspect agent stderr/stdout and retry only after fixing configuration or prompt scope.",
    ),
    "UNKNOWN": FailureClass(
        "UNKNOWN",
        "Unclassified failure",
        "The platform could not map this error to a known workflow failure class.",
        "manual inspection",
        "Inspect run-log.md, effective prompts, artifacts, and validation evidence before retrying.",
    ),
}


def _text(value: Any) -> str:
    return str(value or "")


def classify_failure(message: Any = None, *, step_key: str | None = None, error_code: str | None = None) -> dict[str, Any]:
    """Return the canonical failure class used by retry, UI, reports, and tests."""
    text = _text(message)
    lower = text.lower()
    code = _text(error_code).upper()

    if any(marker in lower for marker in ["outside project", "project guard", "unsafe file path", "parent-directory", "absolute path"]):
        return _FAILURES["PROJECT_GUARD_BLOCKED"].as_dict()
    if code in {"PROJECT_DIFF_MISSING", "NO_PROJECT_CHANGES"} or any(
        marker in lower for marker in ["no files changed", "project changes were required", "did not directly create or modify", "did not create or modify"]
    ):
        return _FAILURES["NO_FILE_CHANGE"].as_dict()
    if code == "VALIDATION_FAILED" or ("validation" in lower and any(marker in lower for marker in ["failed", "assertion", "non-zero", "exit code", "error"])):
        return _FAILURES["VALIDATION_FAILED"].as_dict()
    if code == "VALIDATION_FILE_NOT_FOUND" or "validation_file_not_found" in lower:
        return _FAILURES["VALIDATION_FILE_NOT_FOUND"].as_dict()
    if code == "VALIDATION_FILE_MUTATED" or "validation_file_mutated" in lower:
        return _FAILURES["VALIDATION_FILE_MUTATED"].as_dict()
    if code == "VALIDATION_NOT_EXECUTED" or "validation_not_executed" in lower or "required user validation did not pass" in lower:
        return _FAILURES["VALIDATION_NOT_EXECUTED"].as_dict()
    if code == "TEST_DEFINITION_INVALID" or "unresolved required fixture arguments" in lower or "test_definition_invalid" in lower:
        return _FAILURES["TEST_DEFINITION_INVALID"].as_dict()
    if code == "TEST_LAYOUT_CONFLICT" or any(
        marker in lower
        for marker in ["test_layout_conflict", "import file mismatch", "is not the same as the test file"]
    ):
        return _FAILURES["TEST_LAYOUT_CONFLICT"].as_dict()
    if any(marker in lower for marker in ["pytest", "unittest", "test_command", "tests failed", "test failed", "assertionerror"]):
        return _FAILURES["TEST_FAILED"].as_dict()
    if "review" in lower and any(marker in lower for marker in ["fail", "failed", "risk", "missing"]):
        return _FAILURES["REVIEW_FAILED"].as_dict()
    if code == "CONTEXT_LIMIT_REACHED" or any(marker in lower for marker in ["context is too large", "maximum context length", "compression status: noop", "hard limit"]):
        return _FAILURES["CONTEXT_LIMIT_REACHED"].as_dict()
    if code in {"AGENT_TIMEOUT"} or "timed out" in lower or "timeout" in lower:
        return _FAILURES["TIMEOUT"].as_dict()
    if code in {"AGENT_OUTPUT_FORMAT"} or any(
        marker in lower for marker in ["tool-call json", "write_file", "edit_file", "file/content/end_file", "file block", "invalid json", "malformed json"]
    ):
        return _FAILURES["INVALID_OUTPUT"].as_dict()
    if code == "EXPECTED_FILES_MISSING" or "expected file(s) not found" in lower or "expected files" in lower and "missing" in lower:
        return _FAILURES["EXPECTED_FILES_MISSING"].as_dict()
    if code == "AGENT_OUTPUT_EMPTY" or "returned empty" in lower or "empty stdout" in lower:
        return _FAILURES["AGENT_EMPTY_OUTPUT"].as_dict()
    if code == "AGENT_PROCESS_FAILED" or "process failed with exit code" in lower:
        return _FAILURES["AGENT_PROCESS_FAILED"].as_dict()
    result = _FAILURES["UNKNOWN"].as_dict()
    if step_key:
        result["step_key"] = step_key
    return result


def classify_step_failure(step: dict[str, Any]) -> dict[str, Any]:
    return classify_failure(step.get("error"), step_key=step.get("key"), error_code=step.get("error_code"))


def classify_run_failures(run: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in run.get("steps") or []:
        if step.get("status") in {"failed", "waiting_input", "cancelled"} or step.get("error"):
            item = classify_step_failure(step)
            item.update({"step_key": step.get("key"), "step_status": step.get("status"), "error": step.get("error")})
            steps.append(item)
    run_class = classify_failure(run.get("error"), error_code=run.get("error_code")) if run.get("error") else None
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "run_failure": run_class,
        "step_failures": steps,
        "has_failures": bool(run_class or steps),
    }


__all__ = ["FailureClass", "classify_failure", "classify_step_failure", "classify_run_failures"]
