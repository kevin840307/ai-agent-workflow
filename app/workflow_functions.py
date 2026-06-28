from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


class WorkflowFunctionError(Exception):
    pass


@dataclass(frozen=True)
class WorkflowFunctionContext:
    run: dict[str, Any]
    output_dir: Path
    project_dir: Path
    root_dir: Path
    read_text: Callable[[Path], str]
    write_text: Callable[[Path, str], None]
    log: Callable[[dict[str, Any], str], Awaitable[None]]
    refresh_artifacts: Callable[[str], Awaitable[None]]


AVAILABLE_WORKFLOW_FUNCTIONS = {
    "validators": [
        {
            "id": "validate_spec",
            "label": "Validate Spec",
            "description": "Check required spec sections and AC IDs.",
        },
        {
            "id": "validate_todo",
            "label": "Validate Todo",
            "description": "Check todo sections, TEST IDs, and AC coverage.",
        },
        {
            "id": "require_status_pass",
            "label": "Require Status PASS",
            "description": "Gate helper for review artifacts that must contain Status: PASS.",
        },
        {
            "id": "run_pytest",
            "label": "Run Pytest",
            "description": "Run the configured Python test command and write output/test-result.md.",
        },
    ],
    "reviewStrategies": [
        {
            "id": "current_session",
            "label": "Current Session Review",
            "description": "Reuse the current agent session and evaluate pass/fail keywords plus confidence threshold.",
        },
        {
            "id": "new_agent",
            "label": "New Agent Review",
            "description": "Run review in a fresh agent session, then evaluate pass/fail keywords plus confidence threshold.",
        },
        {
            "id": "multi_agent",
            "label": "Multi-Agent Review",
            "description": "Run one or more reviewer agents and aggregate with keyword_confidence, majority_vote, or all_must_pass.",
        },
    ],
    "aggregators": [
        {
            "id": "keyword_confidence",
            "label": "Keyword + Confidence",
            "description": "Combine pass/fail keywords with a confidence threshold.",
        },
        {
            "id": "majority_vote",
            "label": "Majority Vote",
            "description": "Pass when most reviewers pass.",
        },
        {
            "id": "all_must_pass",
            "label": "All Must Pass",
            "description": "Pass only when every reviewer passes.",
        },
    ],
    "promptParams": [
        {"id": "requirement", "label": "Requirement", "description": "Main user input from the runner composer.", "sample": "Create a controllable agent workflow UI."},
        {"id": "project_path", "label": "Project Path", "description": "Current project folder path.", "sample": "C:\\Users\\kevin\\sort"},
        {"id": "workspace_path", "label": "Workspace Path", "description": "Workflow run workspace path.", "sample": "runs/workflow-001"},
        {"id": "project_overview", "label": "Project Overview", "description": "Auto-generated overview of project files and folders.", "sample": "Project files:\n- app/main.py"},
        {"id": "architecture", "label": "Architecture", "description": "Content of architecture.md from the selected project path.", "sample": "# Architecture\nFastAPI backend with static frontend."},
        {"id": "spec", "label": "Spec", "description": "Content of output/spec.md.", "sample": "## Goal\nBuild the requested workflow feature."},
        {"id": "spec_review", "label": "Spec Review", "description": "Content of output/spec-review.md.", "sample": "Status: PASS"},
        {"id": "todo", "label": "Todo", "description": "Content of output/todo.md.", "sample": "## Todo List\n- TODO-001 Implement UI."},
        {"id": "todo_review", "label": "Todo Review", "description": "Content of output/todo-review.md.", "sample": "Status: PASS"},
        {"id": "test_plan", "label": "Test Plan", "description": "Content of output/test-plan.md.", "sample": "## Test Plan\n- TEST-001 Verify output."},
        {"id": "test_result", "label": "Test Result", "description": "Content of output/test-result.md.", "sample": "Status: FAIL\nAssertionError: expected file missing."},
        {"id": "build_result", "label": "Build Result", "description": "Content of output/build-result.md.", "sample": "FILE: app/main.py\nCONTENT:\n..."},
        {"id": "final_review", "label": "Final Review", "description": "Content of output/final-review.md.", "sample": "Status: PASS"},
        {"id": "raw_spec", "label": "Raw Spec", "description": "Alias of output/spec.md for older templates.", "sample": "## Goal\nBuild the requested workflow feature."},
        {"id": "answers", "label": "Answers", "description": "User answers from previous workflow interaction.", "sample": "Use Python and FastAPI."},
        {"id": "guidance", "label": "Guidance", "description": "User guidance added during the workflow.", "sample": "Keep implementation minimal."},
        {"id": "last_error", "label": "Last Error", "description": "Latest validation, review, timeout, or runner error.", "sample": "Missing Acceptance Criteria section."},
        {"id": "failure_feedback", "label": "Failure Feedback", "description": "Accumulated failure feedback for retry prompts.", "sample": "Retry 1/2 from build: tests failed."},
        {"id": "step_output", "label": "Step Output", "description": "Current step output text when available.", "sample": "Step completed successfully."},
    ],
}


def ids_with_prefix(text: str, prefix: str) -> set[str]:
    import re

    return set(re.findall(rf"\b{prefix}-\d{{3}}\b", text))


def require_sections(text: str, sections: list[str], filename: str) -> None:
    missing = [section for section in sections if f"## {section}" not in text]
    if missing:
        raise WorkflowFunctionError(f"{filename} missing sections: {', '.join(missing)}")


def validate_spec(ctx: WorkflowFunctionContext, artifact: str = "spec.md") -> None:
    text = ctx.read_text(ctx.output_dir / artifact)
    if not text.strip():
        raise WorkflowFunctionError(f"{artifact} is empty.")
    require_sections(
        text,
        ["Goal", "Scope", "Out of Scope", "Input", "Output", "Rules", "Acceptance Criteria", "Unknowns"],
        artifact,
    )
    ac_ids = ids_with_prefix(text, "AC")
    if "AC-001" not in ac_ids:
        raise WorkflowFunctionError(f"{artifact} must include AC-001.")
    if len(ac_ids) != len(list(ac_ids)):
        raise WorkflowFunctionError(f"{artifact} has duplicate AC IDs.")


def validate_todo(ctx: WorkflowFunctionContext, artifact: str = "todo.md") -> None:
    spec = ctx.read_text(ctx.output_dir / "spec.md")
    todo = ctx.read_text(ctx.output_dir / artifact)
    if not todo.strip():
        raise WorkflowFunctionError(f"{artifact} is empty.")
    require_sections(todo, ["Todo List", "Test Plan", "Done Criteria"], artifact)
    if "TODO-001" not in ids_with_prefix(todo, "TODO"):
        raise WorkflowFunctionError(f"{artifact} must include TODO-001.")
    if "TEST-001" not in ids_with_prefix(todo, "TEST"):
        raise WorkflowFunctionError(f"{artifact} must include TEST-001.")
    missing = sorted(ac for ac in ids_with_prefix(spec, "AC") if ac not in todo)
    if missing:
        raise WorkflowFunctionError(f"{artifact} does not reference all AC IDs: {', '.join(missing)}")


def require_status_pass(ctx: WorkflowFunctionContext, artifact: str) -> None:
    text = ctx.read_text(ctx.output_dir / artifact)
    if "Status: PASS" not in text:
        raise WorkflowFunctionError(f"{artifact} must contain 'Status: PASS'.")


def summarize_command_failure(stdout: str, stderr: str) -> str:
    combined = "\n".join(part.strip() for part in [stdout, stderr] if part.strip())
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    important = [
        line
        for line in lines
        if "FAILED" in line
        or "ERROR" in line
        or "Error:" in line
        or "Traceback" in line
        or "ModuleNotFoundError" in line
        or "AssertionError" in line
        or "ImportError" in line
    ]
    selected = important[:6] or lines[-6:]
    return "\n".join(selected).strip()


async def run_pytest(ctx: WorkflowFunctionContext) -> None:
    command = ctx.run.get("test_command") or os.environ.get("WORKFLOW_TEST_COMMAND", "python -m pytest")
    await ctx.log(ctx.run, f"run_test: executing `{command}` in {ctx.project_dir}")

    def execute() -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=str(ctx.project_dir),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    proc = await asyncio.to_thread(execute)
    result = f"Command: {command}\nExitCode: {proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}\n"
    ctx.write_text(Path(ctx.run["workspace"]) / "output" / "test-result.md", result)
    await ctx.refresh_artifacts(ctx.run["id"])
    if proc.returncode != 0:
        summary = summarize_command_failure(proc.stdout, proc.stderr)
        detail = f"\n\nSummary:\n{summary}" if summary else ""
        raise WorkflowFunctionError(
            f"Test command failed with exit code {proc.returncode}. "
            "Open output/test-result.md for full stdout/stderr."
            f"{detail}"
        )


PYTHON_FUNCTIONS = {
    "validate_spec": validate_spec,
    "validate_todo": validate_todo,
    "require_status_pass": require_status_pass,
    "run_pytest": run_pytest,
}
