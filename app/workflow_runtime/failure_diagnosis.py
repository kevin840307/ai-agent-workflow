from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentFailureDiagnosis:
    code: str
    title: str
    explanation: str
    suggested_action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "explanation": self.explanation,
            "suggested_action": self.suggested_action,
        }


_DIAGNOSES = {
    "NO_PROJECT_CHANGES": AgentFailureDiagnosis(
        "NO_PROJECT_CHANGES",
        "Agent did not modify project files",
        "The agent replied or summarized, but the controller did not detect real changes under Project Path.",
        "Retry the same task in the same session with a direct-edit repair prompt. Ask the agent to modify files, not explain only.",
    ),
    "TOOL_CALL_JSON": AgentFailureDiagnosis(
        "TOOL_CALL_JSON",
        "Agent returned tool-call JSON",
        "The agent produced edit_file/write_file style JSON instead of using its own CLI file-edit capability.",
        "Retry with a shorter instruction: use Qwen/OpenCode file edit/write tools directly; do not output tool-call JSON.",
    ),
    "SHELL_COMMAND_PROMPT": AgentFailureDiagnosis(
        "SHELL_COMMAND_PROMPT",
        "Planner produced shell commands",
        "A generated task prompt looks like mkdir/echo/redirection instead of a human CLI instruction.",
        "Retry the planning step and ask for natural-language task prompts only.",
    ),
    "FILE_BLOCK_OUTPUT": AgentFailureDiagnosis(
        "FILE_BLOCK_OUTPUT",
        "Agent emitted FILE blocks",
        "The agent returned file block artifacts instead of directly editing the project. Real mode does not materialize these blocks.",
        "Retry with a direct-edit instruction. Do not use FILE blocks in any runtime mode.",
    ),
    "TEST_ONLY_CHANGE": AgentFailureDiagnosis(
        "TEST_ONLY_CHANGE",
        "Agent changed tests only",
        "The run expected production changes, but only test files were changed.",
        "Retry the implementation task and ask the agent to update the production files required by the SPEC.",
    ),
    "VALIDATION_FAILED": AgentFailureDiagnosis(
        "VALIDATION_FAILED",
        "Validation failed",
        "The project changed, but test_command or validation.py reported a failure.",
        "Send the validation error back to the execution step as repair feedback.",
    ),
    "AGENT_TIMEOUT": AgentFailureDiagnosis(
        "AGENT_TIMEOUT",
        "Agent timed out",
        "The CLI agent or validation process exceeded the configured timeout.",
        "Retry with a smaller task prompt, or increase timeout for this workflow/step.",
    ),
    "AGENT_EMPTY_OUTPUT": AgentFailureDiagnosis(
        "AGENT_EMPTY_OUTPUT",
        "Agent returned empty output",
        "The CLI process completed without usable output or file changes.",
        "Retry the same task; if repeated, replan into smaller prompts or verify the CLI command is configured correctly.",
    ),
    "EXPECTED_FILES_MISSING": AgentFailureDiagnosis(
        "EXPECTED_FILES_MISSING",
        "Expected artifact missing",
        "The workflow expected an output artifact or generated prompt file that was not created.",
        "Retry the producing step; if repeated, inspect the planner output schema and expectedFiles contract.",
    ),
    "UNKNOWN": AgentFailureDiagnosis(
        "UNKNOWN",
        "Unclassified workflow failure",
        "The controller could not map this failure to a known agent behavior class.",
        "Inspect the effective prompt, agent output, run-log, and gate report before retrying.",
    ),
}


def diagnose_agent_failure(message: str | BaseException | None, *, step_key: str | None = None, error_code: str | None = None) -> dict[str, str]:
    text = str(message or "")
    lower = text.lower()
    code = str(error_code or "").upper()
    if "tool-call json" in lower or "edit_file" in lower or "write_file" in lower:
        return _DIAGNOSES["TOOL_CALL_JSON"].as_dict()
    if "file block" in lower or "file/content/end_file" in lower or "end_file" in lower:
        return _DIAGNOSES["FILE_BLOCK_OUTPUT"].as_dict()
    if "shell command" in lower or "mkdir" in lower and "prompt" in lower or "echo" in lower and "prompt" in lower:
        return _DIAGNOSES["SHELL_COMMAND_PROMPT"].as_dict()
    if "only changed test" in lower or "only test" in lower and "production" in lower:
        return _DIAGNOSES["TEST_ONLY_CHANGE"].as_dict()
    if "did not directly create or modify" in lower or "project changes were required" in lower or "no files changed" in lower:
        return _DIAGNOSES["NO_PROJECT_CHANGES"].as_dict()
    if "validation" in lower and ("fail" in lower or "failed" in lower or "error" in lower) or code == "VALIDATION_FAILED":
        return _DIAGNOSES["VALIDATION_FAILED"].as_dict()
    if "timed out" in lower or "timeout" in lower:
        return _DIAGNOSES["AGENT_TIMEOUT"].as_dict()
    if "returned empty" in lower or "empty stdout" in lower:
        return _DIAGNOSES["AGENT_EMPTY_OUTPUT"].as_dict()
    if "expected file(s) not found" in lower or code == "EXPECTED_FILES_MISSING":
        return _DIAGNOSES["EXPECTED_FILES_MISSING"].as_dict()
    return _DIAGNOSES["UNKNOWN"].as_dict()


def summarize_failure_diagnosis(message: str | BaseException | None, *, step_key: str | None = None, error_code: str | None = None) -> str:
    diag = diagnose_agent_failure(message, step_key=step_key, error_code=error_code)
    return f"{diag['code']}: {diag['title']} - {diag['suggested_action']}"


__all__ = ["diagnose_agent_failure", "summarize_failure_diagnosis", "AgentFailureDiagnosis"]
