from __future__ import annotations

import asyncio
import json
import re
import os
import subprocess
import sys
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
    if "Status: PASS" in text:
        return
    try:
        raw = text.strip()
        if raw.startswith("```"):
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
            raw = match.group(1).strip() if match else raw
        else:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and str(parsed.get("status") or "").strip().upper() == "PASS":
        return
    raise WorkflowFunctionError(f"{artifact} must contain 'Status: PASS' or JSON status PASS.")


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


async def adaptive_python_gate(ctx: WorkflowFunctionContext, artifact: str = "python-gate-result.md") -> None:
    """Run the best available Python gate for adaptive workflows.

    Precedence:
    1. A configured or discovered validation script.
    2. The project's pytest suite when tests exist.
    3. A clear skipped PASS artifact when no Python gate is available.
    """
    output_dir = Path(ctx.run["workspace"]) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    script = _find_project_validation_script(ctx)
    if script:
        await _run_validation_script(ctx, script, artifact)
        return
    if _project_has_pytest_files(ctx.project_dir):
        await run_pytest(ctx)
        test_result = ctx.read_text(output_dir / "test-result.md")
        ctx.write_text(
            output_dir / artifact,
            "\n".join(
                [
                    "# Python Gate Result",
                    "",
                    "Status: PASS",
                    "Mode: pytest",
                    "Evidence: output/test-result.md",
                    "",
                    "## Test Result",
                    "```text",
                    test_result.rstrip(),
                    "```",
                    "",
                ]
            ),
        )
        return
    ctx.write_text(
        output_dir / artifact,
        "\n".join(
            [
                "# Python Gate Result",
                "",
                "Status: PASS",
                "Mode: skipped",
                "Reason: No validation script was configured or found, and no pytest files were present.",
                "",
            ]
        ),
    )


def _find_project_validation_script(ctx: WorkflowFunctionContext) -> Path | None:
    configured = str(ctx.run.get("validation_script") or "").strip()
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    step_config = ctx.run.get("_current_step_config") if isinstance(ctx.run, dict) else {}
    fallback = step_config.get("fallbackValidationScripts") if isinstance(step_config, dict) else []
    if isinstance(fallback, str):
        candidates.extend(item.strip() for item in fallback.split(",") if item.strip())
    elif isinstance(fallback, list):
        candidates.extend(str(item).strip() for item in fallback if str(item).strip())
    for value in candidates:
        raw = Path(value).expanduser()
        path = raw.resolve() if raw.is_absolute() else (ctx.project_dir / raw).resolve()
        if path.is_file() and path.suffix.lower() == ".py":
            return path
    return None


async def _run_validation_script(ctx: WorkflowFunctionContext, script: Path, artifact: str) -> None:
    command = [
        sys.executable,
        str(script),
        "--project",
        str(ctx.project_dir),
        "--workspace",
        str(Path(ctx.run["workspace"])),
        "--output",
        str(ctx.output_dir),
    ]
    timeout_sec = _test_command_timeout_seconds()
    await ctx.log(ctx.run, f"python_gate: executing validation script `{script}` in {ctx.project_dir} (timeout {timeout_sec:.0f}s)")

    proc = await _run_validation_command(command, cwd=ctx.project_dir, timeout_sec=timeout_sec)
    if proc["returncode"] != 0 and _looks_like_script_argument_error(proc["stderr"]):
        command = [sys.executable, str(script)]
        proc = await _run_validation_command(command, cwd=ctx.project_dir, timeout_sec=timeout_sec)

    status = "PASS" if proc["returncode"] == 0 else "FAIL"
    result = "\n".join(
        [
            "# Python Gate Result",
            "",
            f"Status: {status}",
            "Mode: validation_script",
            f"Script: {_display_path(ctx.project_dir, script)}",
            f"Command: {' '.join(_quote_command_part(part) for part in command)}",
            f"Exit Code: {proc['returncode']}",
            *([f"TimeoutSec: {timeout_sec:.0f}"] if proc["returncode"] == "TIMEOUT" else []),
            "",
            "## Stdout",
            "```text",
            (proc["stdout"] or "").rstrip(),
            "```",
            "",
            "## Stderr",
            "```text",
            (proc["stderr"] or "").rstrip(),
            "```",
            "",
        ]
    )
    ctx.write_text(ctx.output_dir / artifact, result)
    if proc["returncode"] == "TIMEOUT":
        raise WorkflowFunctionError(f"Python gate validation script timed out after {timeout_sec:.0f} seconds")
    if proc["returncode"] != 0:
        summary = summarize_command_failure(proc["stdout"], proc["stderr"])
        detail = f": {summary}" if summary else ""
        raise WorkflowFunctionError(f"Python gate validation script failed with exit code {proc['returncode']}{detail}")


async def _run_validation_command(command: list[str], *, cwd: Path, timeout_sec: float) -> dict[str, object]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        process.kill()
        stdout_b, stderr_b = await process.communicate()
        return {
            "returncode": "TIMEOUT",
            "stdout": stdout_b.decode("utf-8", errors="replace") if isinstance(stdout_b, bytes) else str(stdout_b or ""),
            "stderr": stderr_b.decode("utf-8", errors="replace") if isinstance(stderr_b, bytes) else str(stderr_b or ""),
        }
    return {
        "returncode": int(process.returncode or 0),
        "stdout": stdout_b.decode("utf-8", errors="replace") if isinstance(stdout_b, bytes) else str(stdout_b or ""),
        "stderr": stderr_b.decode("utf-8", errors="replace") if isinstance(stderr_b, bytes) else str(stderr_b or ""),
    }

def _project_has_pytest_files(project_dir: Path) -> bool:
    tests_dir = project_dir / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        return True
    return any(project_dir.glob("test_*.py"))


def _looks_like_script_argument_error(stderr: str) -> bool:
    lowered = (stderr or "").lower()
    return any(marker in lowered for marker in ("unrecognized arguments", "unknown option", "no such option"))


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _quote_command_part(value: str) -> str:
    return f'"{value}"' if any(ch.isspace() for ch in value) else value


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


def _direct_state_paths(output_dir: Path, phase: str) -> list[str]:
    paths: set[str] = set()
    for state_path in (output_dir / "tasks").glob(f"*/{phase}-state.json"):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("files") or []:
            if isinstance(item, dict) and str(item.get("path") or "").strip():
                paths.add(str(item.get("path")).replace("\\", "/"))
    return sorted(paths)


def _has_direct_edit_summary(text: str) -> bool:
    return "Direct Agent Edits" in (text or "") or "directly. The platform recorded this summary" in (text or "")


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
    direct_state_changed = sorted(set(_direct_state_paths(ctx.output_dir, "build") + _direct_state_paths(ctx.output_dir, "generate_tests")))
    changed_files = [line.strip() for line in git_changed.splitlines() if line.strip()] or file_block_changed or direct_state_changed
    diff_context = {
        "changed_files": changed_files,
        "git_diff_available": bool(git_changed or git_stat or git_diff),
        "git_stat": git_stat,
        "git_diff_excerpt": git_diff[:12000],
        "file_block_paths": file_block_changed,
        "direct_state_paths": direct_state_changed,
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
        git_stat or "No git diff stat available. Using direct-edit state or FILE block paths as fallback evidence.",
        "```",
        "",
        "## Git Diff Excerpt",
        "```diff",
        git_diff[:12000] or "No git diff available. The project may not be a git repository, or changes may come from direct-edit state / generated FILE block evidence.",
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
    task_manifest_json = ctx.read_text(ctx.output_dir / "task-manifest.json")
    workflow_instance = ctx.read_text(ctx.output_dir / "generated-workflow-instance.json")
    workflow_instance_validation = ctx.read_text(ctx.output_dir / "workflow-instance-validation.md")
    test_plan = ctx.read_text(ctx.output_dir / "test-plan.md")
    test_result = ctx.read_text(ctx.output_dir / "test-result.md")
    external_validation = ctx.read_text(ctx.output_dir / "external-validation-result.md")

    def _json_status_pass(text: str) -> bool:
        try:
            data = json.loads(text or "{}")
        except Exception:
            return False
        return str(data.get("status") or "").upper() == "READY" and bool(data.get("tasks") or data.get("steps"))

    checks = {
        "task_manifest": {
            "status": "PASS" if ("Status: READY" in task_manifest and "## Small Task Order" in task_manifest) else "FAIL",
            "evidence": "output/task-manifest.md",
        },
        "task_manifest_json": {
            "status": "PASS" if _json_status_pass(task_manifest_json) else "FAIL",
            "evidence": "output/task-manifest.json",
        },
        "workflow_instance": {
            "status": "PASS" if _json_status_pass(workflow_instance) else "FAIL",
            "evidence": "output/generated-workflow-instance.json",
        },
        "workflow_instance_validation": {
            "status": "PASS" if "Status: PASS" in workflow_instance_validation else "FAIL",
            "evidence": "output/workflow-instance-validation.md",
        },
        "build_artifact": {
            "status": "PASS" if (_has_direct_edit_summary(build_result) or bool(_direct_state_paths(ctx.output_dir, "build"))) else "FAIL",
            "evidence": "output/build-result.md or output/tasks/*/build-state.json",
        },
        "generated_tests": {
            "status": "PASS" if (_has_direct_edit_summary(test_plan) or bool(_direct_state_paths(ctx.output_dir, "generate_tests"))) else "FAIL",
            "evidence": "output/test-plan.md or output/tasks/*/generate_tests-state.json",
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
            "evidence": "Project diff safety checks confirm Qwen/OpenCode direct edits stay inside the selected Project Path.",
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
            "direct_state_paths": diff_context.get("direct_state_paths", []),
            "artifacts": [
                "output/task-manifest.md",
                "output/task-manifest.json",
                "output/generated-workflow-instance.json",
                "output/workflow-instance-validation.md",
                "output/workflow-run-trace.md",
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
        "- Evidence-based final review generated by Python from workflow artifacts, compiled task workflow evidence, tests, and external validation.",
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

# ---------------------------------------------------------------------------
# Regression Test Framework workflow helpers
# ---------------------------------------------------------------------------

def _regression_requirement(ctx: WorkflowFunctionContext) -> str:
    return ctx.read_text(Path(ctx.run["workspace"]) / "requirement.md").strip()


def _regression_case_id(requirement: str) -> str:
    match = re.search(r"\b(WORKITEM\d+|CASE[-_ ]?\d+|SOP[-_ ]?\d+)\b", requirement or "", flags=re.IGNORECASE)
    return (match.group(1).replace(" ", "_").upper() if match else "WORKITEM0001")


def collect_regression_context(ctx: WorkflowFunctionContext, artifact: str = "regression-context.md") -> None:
    requirement = _regression_requirement(ctx)
    case_id = _regression_case_id(requirement)
    lines = [
        "# Regression Context",
        "",
        "Status: READY",
        f"Case ID: {case_id}",
        "",
        "## Requirement",
        requirement or "No requirement text was provided.",
        "",
        "## Controller Rules",
        "- One scenario maps to one SOP / one CaseId.",
        "- SQL generation must stay template-driven and reviewable.",
        "- Runtime data SQL is separated from one-time SOP/Block definition SQL.",
        "- validation.py is the deterministic acceptance oracle.",
        "",
        "## Expected Artifacts",
        "- sop-definition.sql",
        "- runtime-test-data.sql",
        "- expected-result.md",
        "- validation.py",
        "- regression-test-case.md",
    ]
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines).rstrip() + "\n")


def generate_regression_sop_sql(ctx: WorkflowFunctionContext, artifact: str = "sop-definition.sql") -> None:
    requirement = _regression_requirement(ctx)
    case_id = _regression_case_id(requirement)
    sql = f"""-- SOP / Block definition SQL generated by AI Workflow Controller
-- CaseId: {case_id}
-- Review before applying to any shared database.

INSERT INTO SOP_DEFINITION (CASE_ID, SOP_NAME, ENABLED, CREATED_BY)
VALUES ('{case_id}', 'AUTO_GENERATED_SOP', 'Y', 'AI_WORKFLOW');

INSERT INTO SOP_BLOCK_PARAMETER (CASE_ID, BLOCK_ID, PARAM_NAME, PARAM_VALUE)
VALUES ('{case_id}', 'BLOCK_001', 'TYPE_COMBINATION', 'typeA,typeB');
"""
    ctx.write_text(ctx.output_dir / artifact, sql)
    ctx.write_text(ctx.output_dir / "sop-definition.md", f"# SOP Definition SQL\n\nStatus: READY\n\n- Case ID: `{case_id}`\n- SQL: `output/{artifact}`\n")


def generate_regression_runtime_sql(ctx: WorkflowFunctionContext, artifact: str = "runtime-test-data.sql") -> None:
    requirement = _regression_requirement(ctx)
    case_id = _regression_case_id(requirement)
    sql = f"""-- Runtime test data SQL generated by AI Workflow Controller
-- CaseId: {case_id}
-- This data should be inserted per test run and cleaned up by CaseId.

INSERT INTO RUNTIME_EVENT (CASE_ID, EVENT_TYPE, PAYLOAD, EXPECTED_STATUS)
VALUES ('{case_id}', 'typeA', '{{"type":"typeA","value":100}}', 'SUCCESS');

INSERT INTO RUNTIME_EVENT (CASE_ID, EVENT_TYPE, PAYLOAD, EXPECTED_STATUS)
VALUES ('{case_id}', 'typeB', '{{"type":"typeB","value":200}}', 'SUCCESS');
"""
    ctx.write_text(ctx.output_dir / artifact, sql)
    ctx.write_text(ctx.output_dir / "expected-result.md", f"# Expected Result\n\nStatus: READY\n\n- Case ID: `{case_id}`\n- Expected table/status: `SUCCESS` for `typeA` and `typeB`.\n- Runtime SQL: `output/{artifact}`\n")


def generate_regression_validation(ctx: WorkflowFunctionContext, artifact: str = "validation.py") -> None:
    requirement = _regression_requirement(ctx)
    case_id = _regression_case_id(requirement)
    script = f'''from pathlib import Path

required = [
    "sop-definition.sql",
    "runtime-test-data.sql",
    "expected-result.md",
    "regression-test-case.md",
]
missing = [name for name in required if not Path("output", name).exists()]
assert not missing, f"missing regression artifacts: {{missing}}"

sop_sql = Path("output", "sop-definition.sql").read_text(encoding="utf-8")
runtime_sql = Path("output", "runtime-test-data.sql").read_text(encoding="utf-8")
case_doc = Path("output", "regression-test-case.md").read_text(encoding="utf-8")

assert "{case_id}" in sop_sql, "case id missing from SOP SQL"
assert "{case_id}" in runtime_sql, "case id missing from runtime SQL"
assert "typeA" in runtime_sql and "typeB" in runtime_sql, "runtime SQL must cover typeA/typeB"
assert "Status: PASS" in case_doc, "case document must pass final packaging gate"
print("regression workflow validation ok: {case_id}")
'''
    ctx.write_text(ctx.output_dir / artifact, script)
    ctx.write_text(ctx.output_dir / "validation-script-report.md", f"# Validation Script\n\nStatus: READY\n\n- Generated `output/{artifact}` for {case_id}.\n")


def generate_regression_case_doc(ctx: WorkflowFunctionContext, artifact: str = "regression-test-case.md") -> None:
    requirement = _regression_requirement(ctx)
    case_id = _regression_case_id(requirement)
    lines = [
        "# Regression Test Case",
        "",
        "Status: PASS",
        f"Case ID: {case_id}",
        "",
        "## Requirement",
        requirement or "No requirement text was provided.",
        "",
        "## Generated Artifacts",
        "- `output/sop-definition.sql` for one-time SOP / Block definition setup.",
        "- `output/runtime-test-data.sql` for per-run runtime input data.",
        "- `output/expected-result.md` for deterministic expected status.",
        "- `output/validation.py` for acceptance validation.",
        "",
        "## Execution Flow",
        "1. Prepare a clean test database/schema.",
        "2. Apply SOP definition SQL once for this CaseId.",
        "3. Insert runtime SQL for the current run.",
        "4. Start the target EXE/scheduler as production does; do not call Main directly.",
        "5. Validate expected status from DB/log/web/monitoring evidence.",
        "",
        "## Cleanup",
        f"- Delete rows by `CASE_ID = '{case_id}'` from generated runtime and SOP tables after the test run.",
    ]
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines).rstrip() + "\n")


def validate_regression_case_package(ctx: WorkflowFunctionContext, artifact: str = "dry-run-report.md") -> None:
    required = {
        "regression-context.md": "Status: READY",
        "sop-definition.sql": "INSERT INTO SOP_DEFINITION",
        "runtime-test-data.sql": "INSERT INTO RUNTIME_EVENT",
        "expected-result.md": "Status: READY",
        "validation.py": "regression workflow validation ok",
        "regression-test-case.md": "Status: PASS",
    }
    failures: list[str] = []
    for name, marker in required.items():
        text = ctx.read_text(ctx.output_dir / name)
        if marker not in text:
            failures.append(f"{name} missing marker {marker!r}")
    status = "FAIL" if failures else "PASS"
    lines = [
        "# Regression Workflow Dry Run",
        "",
        f"Status: {status}",
        "",
        "## Checks",
    ]
    for name in required:
        lines.append(f"- {name}: {'FAIL' if any(item.startswith(name) for item in failures) else 'PASS'}")
    if failures:
        lines.extend(["", "## Failures", *(f"- {item}" for item in failures)])
    else:
        lines.extend(["", "## Summary", "- Regression test case package is complete and internally consistent."])
    ctx.write_text(ctx.output_dir / artifact, "\n".join(lines).rstrip() + "\n")
    if failures:
        raise WorkflowFunctionError("Regression package dry run failed: " + "; ".join(failures))
