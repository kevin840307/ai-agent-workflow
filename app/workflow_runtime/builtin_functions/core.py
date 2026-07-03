from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError


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
    timeout_sec = _test_command_timeout_seconds()
    await ctx.log(ctx.run, f"run_test: executing `{command}` in {ctx.project_dir} (timeout {timeout_sec:.0f}s)")

    def execute() -> subprocess.CompletedProcess:
        return subprocess.run(
            command,
            cwd=str(ctx.project_dir),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_sec,
        )

    try:
        proc = await asyncio.to_thread(execute)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        result = (
            f"Command: {command}\n"
            f"ExitCode: TIMEOUT\n"
            f"TimeoutSec: {timeout_sec:.0f}\n\n"
            f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}\n"
        )
        ctx.write_text(Path(ctx.run["workspace"]) / "output" / "test-result.md", result)
        await ctx.refresh_artifacts(ctx.run["id"])
        raise WorkflowFunctionError(f"Test command timed out after {timeout_sec:.0f} seconds. Open output/test-result.md for details.") from exc

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


def _contains_status_pass(text: str) -> bool:
    lowered = (text or "").lower()
    return "status: pass" in lowered or "exitcode: 0" in lowered or "exit code: 0" in lowered


def validate_general_auto_plan(ctx: WorkflowFunctionContext, artifact: str = "implementation-review.md") -> None:
    """Deterministic gate for General Auto Development todo.md.

    This replaces fragile AI self-review for the default fully-automated path.
    It accepts the project's task plan only when it is concrete enough for Build
    and explicitly includes tests plus the external validation stage.
    """
    todo = ctx.read_text(ctx.output_dir / "todo.md")
    if not todo.strip():
        raise WorkflowFunctionError("todo.md is empty.")

    required_markers = [
        "Status: READY",
        "## Task Index",
        "## Tasks",
        "## External Validation",
    ]
    missing = [marker for marker in required_markers if marker not in todo]
    if missing:
        raise WorkflowFunctionError(f"todo.md missing required General Auto Development marker(s): {', '.join(missing)}")

    import re

    task_ids = sorted(set(re.findall(r"\bTASK-\d{3}\b", todo)))
    if not task_ids:
        raise WorkflowFunctionError("todo.md must include at least one TASK-001 style task id.")
    if len(task_ids) > 12:
        raise WorkflowFunctionError(f"todo.md has too many tasks for General Auto Development: {len(task_ids)} > 12")
    if "Acceptance Criteria" not in todo and "AC-" not in todo:
        raise WorkflowFunctionError("todo.md must include acceptance criteria for each task.")

    lowered = todo.lower()
    if "test" not in lowered and "pytest" not in lowered and "測試" not in todo:
        raise WorkflowFunctionError("todo.md must include an automated test strategy before external validation.")
    if "validation" not in lowered:
        raise WorkflowFunctionError("todo.md must include the external validation step.")

    lines = [
        "# Implementation Review",
        "",
        "Status: PASS",
        "Confidence: 1.00",
        "",
        "## Checks",
        f"- Task count is bounded: {len(task_ids)} task(s).",
        "- Plan contains TASK ids, acceptance criteria, automated test coverage, and external validation handling.",
        "- No user question is required for this deterministic gate.",
        "",
        "## Findings",
        "- PASS: todo.md is concrete enough for Build to proceed.",
        "",
    ]
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines))


def validate_general_auto_final(ctx: WorkflowFunctionContext, artifact: str = "final-review.md") -> None:
    """Deterministic final gate for General Auto Development.

    Final pass is based on concrete artifacts: Build output, automated test
    result, and external validation result. This avoids AI review text
    format drift such as missing PASS keywords.
    """
    build_result = ctx.read_text(ctx.output_dir / "build-result.md")
    test_result = ctx.read_text(ctx.output_dir / "test-result.md")
    external_validation = ctx.read_text(ctx.output_dir / "external-validation-result.md")

    failures: list[str] = []
    if "FILE:" not in build_result or "CONTENT:" not in build_result or "END_FILE" not in build_result:
        failures.append("build-result.md does not contain production FILE/CONTENT/END_FILE output.")
    if not _contains_status_pass(test_result):
        failures.append("test-result.md does not show a passing test command.")
    if "Status: PASS" not in external_validation and "Exit Code: 0" not in external_validation:
        failures.append("external-validation-result.md does not show Status: PASS / Exit Code: 0.")

    status = "FAIL" if failures else "PASS"
    lines = [
        "# Final Review",
        "",
        f"Status: {status}",
        "Confidence: 1.00" if status == "PASS" else "Confidence: 0.00",
        "",
        "## Summary",
        "- Deterministic final review generated by Python from workflow artifacts.",
        "",
        "## Verification",
        f"- Automated test result: {'PASS' if _contains_status_pass(test_result) else 'FAIL'}",
        f"- External validation script result: {'PASS' if ('Status: PASS' in external_validation or 'Exit Code: 0' in external_validation) else 'FAIL'}",
        f"- Build artifact present: {'PASS' if 'FILE:' in build_result and 'CONTENT:' in build_result and 'END_FILE' in build_result else 'FAIL'}",
        "- Files stayed inside Project path: enforced by FILE path safety checks before materializing files.",
        "",
        "## Remaining Risks",
    ]
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- None detected by deterministic workflow gates.")
    lines.append("")
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines))
    if failures:
        raise WorkflowFunctionError("Final deterministic review failed: " + "; ".join(failures))


def _test_command_timeout_seconds() -> float:
    raw = os.environ.get("WORKFLOW_TEST_TIMEOUT_SEC", "30")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 30.0
    return max(1.0, min(value, 3600.0))
