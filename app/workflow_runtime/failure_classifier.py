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

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "description": self.description,
            "retry_target": self.retry_target,
            "repair_prompt_hint": self.repair_prompt_hint,
            "severity": self.severity,
        }


_FAILURES: dict[str, FailureClass] = {
    "NO_FILE_CHANGE": FailureClass(
        "NO_FILE_CHANGE",
        "Agent did not change project files",
        "The workflow expected real project edits, but no changed files were detected under Project Path.",
        "implementation step",
        "Directly create or modify the required files in the selected project. Do not only explain the plan.",
        "high",
    ),
    "VALIDATION_FAILED": FailureClass(
        "VALIDATION_FAILED",
        "Validation script failed",
        "The user/project validation script exited non-zero or reported an assertion failure.",
        "implementation step",
        "Use the validation stdout/stderr as the acceptance oracle and repair production files until validation.py exits 0.",
        "high",
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
    if any(marker in lower for marker in ["pytest", "unittest", "test_command", "tests failed", "test failed", "assertionerror"]):
        return _FAILURES["TEST_FAILED"].as_dict()
    if "review" in lower and any(marker in lower for marker in ["fail", "failed", "risk", "missing"]):
        return _FAILURES["REVIEW_FAILED"].as_dict()
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
