from __future__ import annotations

from app.runtime_modules.errors import UserInputRequired, ValidationError, WorkflowCancelled, WorkflowError


ERROR_AGENT_CLI_NOT_FOUND = "AGENT_CLI_NOT_FOUND"
ERROR_AGENT_OUTPUT_EMPTY = "AGENT_OUTPUT_EMPTY"
ERROR_AGENT_OUTPUT_FORMAT = "AGENT_OUTPUT_FORMAT"
ERROR_AGENT_SESSION = "AGENT_SESSION_RECOVERABLE"
ERROR_CONTEXT_LIMIT = "CONTEXT_LIMIT_REACHED"
ERROR_AGENT_TIMEOUT = "AGENT_TIMEOUT"
ERROR_AGENT_PROCESS = "AGENT_PROCESS_FAILED"
ERROR_CONFIG_INVALID = "WORKFLOW_CONFIG_INVALID"
ERROR_EXPECTED_FILES = "EXPECTED_FILES_MISSING"
ERROR_PROJECT_DIFF = "PROJECT_DIFF_MISSING"
ERROR_USER_INPUT_REQUIRED = "USER_INPUT_REQUIRED"
ERROR_VALIDATION = "VALIDATION_FAILED"
ERROR_VALIDATION_FILE_NOT_FOUND = "VALIDATION_FILE_NOT_FOUND"
ERROR_VALIDATION_FILE_MUTATED = "VALIDATION_FILE_MUTATED"
ERROR_VALIDATION_NOT_EXECUTED = "VALIDATION_NOT_EXECUTED"
ERROR_TEST_DEFINITION_INVALID = "TEST_DEFINITION_INVALID"
ERROR_WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"
ERROR_WORKFLOW_FAILED = "WORKFLOW_FAILED"

CONTEXT_LIMIT_MARKERS = (
    "context is too large",
    "maximum context length",
    "context window",
    "compression status: noop",
    "hard limit",
    "too many tokens",
)


SESSION_RECOVERY_MARKERS = (
    "session not found",
    "invalid session",
    "unknown session",
    "could not find session",
    "no session found",
    "no saved session found",
    "session is already in use",
    "already in use",
    "already exists",
    "active or archived",
    "delete or unarchive",
)


def is_recoverable_session_error(exc: BaseException | str) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in SESSION_RECOVERY_MARKERS)



def is_context_limit_error(exc: BaseException | str) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in CONTEXT_LIMIT_MARKERS)


def classify_exception(exc: BaseException | str) -> str:
    if isinstance(exc, WorkflowCancelled):
        return ERROR_WORKFLOW_CANCELLED
    if isinstance(exc, UserInputRequired):
        return ERROR_USER_INPUT_REQUIRED
    if isinstance(exc, ValidationError):
        return ERROR_VALIDATION

    message = str(exc).lower()
    if is_context_limit_error(message):
        return ERROR_CONTEXT_LIMIT
    if is_recoverable_session_error(message):
        return ERROR_AGENT_SESSION
    if "cli not found" in message:
        return ERROR_AGENT_CLI_NOT_FOUND
    if "timed out" in message or "timeout" in message:
        return ERROR_AGENT_TIMEOUT
    if "returned empty" in message or "empty stdout" in message:
        return ERROR_AGENT_OUTPUT_EMPTY
    if "tool-call json" in message or "artifact content" in message or "did not treat the prompt file" in message:
        return ERROR_AGENT_OUTPUT_FORMAT
    if "process failed with exit code" in message:
        return ERROR_AGENT_PROCESS
    if "validation_file_not_found" in message:
        return ERROR_VALIDATION_FILE_NOT_FOUND
    if "validation_file_mutated" in message:
        return ERROR_VALIDATION_FILE_MUTATED
    if "validation_not_executed" in message or "required user validation did not pass" in message:
        return ERROR_VALIDATION_NOT_EXECUTED
    if "unresolved required fixture arguments" in message or "test_definition_invalid" in message:
        return ERROR_TEST_DEFINITION_INVALID
    if "expected file(s) not found" in message:
        return ERROR_EXPECTED_FILES
    if "did not create or modify" in message or "project changes" in message:
        return ERROR_PROJECT_DIFF
    if isinstance(exc, WorkflowError):
        return ERROR_WORKFLOW_FAILED
    return ERROR_WORKFLOW_FAILED
