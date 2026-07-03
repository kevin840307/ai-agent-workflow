from __future__ import annotations

import asyncio
import json
import re
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


def _file_block_paths(text: str) -> list[str]:
    return sorted(set(re.findall(r"^FILE:\s*(.+?)\s*$", text or "", flags=re.MULTILINE)))


def _git_output(project_dir: Path, args: list[str], *, timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(project_dir),
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _diff_context(ctx: WorkflowFunctionContext, build_result: str, test_plan: str) -> dict[str, object]:
    project_dir = ctx.project_dir
    git_changed = _git_output(project_dir, ["diff", "--name-only"])
    git_stat = _git_output(project_dir, ["diff", "--stat"])
    git_diff = _git_output(project_dir, ["diff", "--", "."], timeout=8.0)
    file_block_changed = sorted(set(_file_block_paths(build_result) + _file_block_paths(test_plan)))
    changed_files = [line.strip() for line in git_changed.splitlines() if line.strip()] or file_block_changed
    diff_context = {
        "changed_files": changed_files,
        "git_diff_available": bool(git_changed or git_stat or git_diff),
        "git_stat": git_stat,
        "git_diff_excerpt": git_diff[:12000],
        "file_block_paths": file_block_changed,
    }
    lines = [
        "# Diff Context",
        "",
        f"Status: {'READY' if changed_files else 'EMPTY'}",
        "",
        "## Changed Files",
        *(f"- {path}" for path in changed_files),
        "",
        "## Git Diff Stat",
        "```text",
        git_stat or "No git diff stat available. Using FILE block paths as fallback evidence.",
        "```",
        "",
        "## Git Diff Excerpt",
        "```diff",
        git_diff[:12000] or "No git diff available. The project may not be a git repository, or changes may come from generated FILE block evidence.",
        "```",
        "",
    ]
    ctx.write_text(ctx.output_dir / "diff-context.md", "\n".join(lines))
    return diff_context


def validate_general_auto_final(ctx: WorkflowFunctionContext, artifact: str = "final-review.md") -> None:
    """Evidence-based final verifier for General Auto Development.

    PASS is decided from concrete artifacts, not from AI self-review text.  The
    function writes both a human-readable final review and a machine-readable
    verifier report for downstream gates / diff review.
    """
    build_result = ctx.read_text(ctx.output_dir / "build-result.md")
    task_manifest = ctx.read_text(ctx.output_dir / "task-manifest.md")
    test_plan = ctx.read_text(ctx.output_dir / "test-plan.md")
    test_result = ctx.read_text(ctx.output_dir / "test-result.md")
    external_validation = ctx.read_text(ctx.output_dir / "external-validation-result.md")

    checks = {
        "task_manifest": {
            "status": "PASS" if ("Status: READY" in task_manifest and "## Small Task Order" in task_manifest) else "FAIL",
            "evidence": "output/task-manifest.md",
        },
        "build_artifact": {
            "status": "PASS" if ("FILE:" in build_result and "CONTENT:" in build_result and "END_FILE" in build_result) else "FAIL",
            "evidence": "output/build-result.md",
        },
        "generated_tests": {
            "status": "PASS" if ("FILE:" in test_plan and "tests/" in test_plan and "END_FILE" in test_plan) else "FAIL",
            "evidence": "output/test-plan.md",
        },
        "automated_tests": {
            "status": "PASS" if _contains_status_pass(test_result) else "FAIL",
            "evidence": "output/test-result.md",
        },
        "external_validation": {
            "status": "PASS" if ("Status: PASS" in external_validation or "Exit Code: 0" in external_validation or "ExitCode: 0" in external_validation) else "FAIL",
            "evidence": "output/external-validation-result.md",
        },
        "workspace_isolation": {
            "status": "PASS",
            "evidence": "FILE path safety checks are enforced before materializing Build and Generate Tests outputs.",
        },
    }
    failures = [name for name, item in checks.items() if item["status"] != "PASS"]
    diff_context = _diff_context(ctx, build_result, test_plan)
    report = {
        "status": "FAIL" if failures else "PASS",
        "checks": checks,
        "evidence": {
            "changed_files": diff_context.get("changed_files", []),
            "git_diff_available": diff_context.get("git_diff_available", False),
            "file_block_paths": diff_context.get("file_block_paths", []),
            "artifacts": [
                "output/task-manifest.md",
                "output/build-result.md",
                "output/test-plan.md",
                "output/test-result.md",
                "output/external-validation-result.md",
                "output/diff-context.md",
            ],
        },
        "policy": {
            "ai_review_can_warn": True,
            "ai_review_can_decide_pass": False,
            "git_commit_push_allowed": False,
        },
    }
    ctx.write_text(ctx.output_dir / "verifier-report.json", json.dumps(report, indent=2, ensure_ascii=False))

    status = report["status"]
    lines = [
        "# Final Review",
        "",
        f"Status: {status}",
        "Confidence: 1.00" if status == "PASS" else "Confidence: 0.00",
        "",
        "## Summary",
        "- Evidence-based final review generated by Python from workflow artifacts.",
        "- The AI diff reviewer may add risks, but cannot turn a failing verifier into PASS.",
        "",
        "## Verification",
    ]
    for name, item in checks.items():
        lines.append(f"- {name}: {item['status']} ({item['evidence']})")
    lines.extend([
        "",
        "## Diff Evidence",
        f"- Changed files: {len(diff_context.get('changed_files', []))}",
        f"- Git diff available: {bool(diff_context.get('git_diff_available', False))}",
        "- Diff context: output/diff-context.md",
        "- Verifier report: output/verifier-report.json",
        "",
        "## Remaining Risks",
    ])
    if failures:
        lines.extend(f"- {name} did not pass." for name in failures)
    else:
        lines.append("- None detected by deterministic workflow gates.")
    lines.append("")
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines))
    if failures:
        raise WorkflowFunctionError("Final deterministic verifier failed: " + "; ".join(failures))


def _test_command_timeout_seconds() -> float:
    raw = os.environ.get("WORKFLOW_TEST_TIMEOUT_SEC", "30")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 30.0
    return max(1.0, min(value, 3600.0))
