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
        {
            "id": "validate_security_report",
            "label": "Validate Security Report",
            "description": "Check output/security-report.md contains the required vulnerability scan sections and finding format.",
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
        {"id": "project_profile", "label": "Project Profile", "description": "Detected language, test framework, source files, and test files from the selected project path.", "sample": "Primary language: Python\nTest framework: pytest"},
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


def _markdown_section_body(text: str, section: str) -> str:
    marker = f"## {section}"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    next_section = text.find("\n## ", start)
    if next_section < 0:
        next_section = len(text)
    return text[start:next_section].strip()


def _ids_with_prefix_ordered(text: str, prefix: str) -> list[str]:
    import re

    return re.findall(rf"\b{prefix}-\d{{3}}\b", text)


def _security_finding_blocks(findings: str) -> list[tuple[str, str]]:
    import re

    matches = list(re.finditer(r"(?m)^###\s+(VULN-\d{3})\b.*$", findings))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(findings)
        blocks.append((match.group(1), findings[start:end].strip()))
    return blocks


def _require_field_in_block(artifact: str, finding_id: str, block: str, field: str) -> str:
    import re

    pattern = rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, block)
    if not match or not match.group(1).strip() or match.group(1).strip() in {"-", "N/A", "TBD", "Unknown"}:
        raise WorkflowFunctionError(f"{artifact} {finding_id} must include non-empty '{field}: ...'.")
    return match.group(1).strip()


def validate_security_report(ctx: WorkflowFunctionContext, artifact: str = "security-report.md") -> None:
    path = ctx.output_dir / artifact
    text = ctx.read_text(path)
    if not text.strip():
        raise WorkflowFunctionError(f"{artifact} is empty.")
    if "Status: DONE" not in text:
        raise WorkflowFunctionError(f"{artifact} must contain 'Status: DONE'.")

    required_sections = [
        "Summary",
        "Scan Scope",
        "Method",
        "Findings",
        "Risk Matrix",
        "Recommendations",
        "Limitations",
    ]
    require_sections(text, required_sections, artifact)

    summary = _markdown_section_body(text, "Summary")
    valid_severities = {"Critical", "High", "Medium", "Low", "Info"}
    valid_confidences = {"High", "Medium", "Low"}
    if not any(f"Overall risk level: {severity}" in summary for severity in valid_severities):
        raise WorkflowFunctionError(
            f"{artifact} Summary must include 'Overall risk level: Critical|High|Medium|Low|Info'."
        )
    if not any(f"Overall confidence: {confidence}" in summary for confidence in valid_confidences):
        raise WorkflowFunctionError(
            f"{artifact} Summary must include 'Overall confidence: High|Medium|Low'."
        )

    findings = _markdown_section_body(text, "Findings")
    if not findings:
        raise WorkflowFunctionError(f"{artifact} Findings section must not be empty.")

    finding_blocks = _security_finding_blocks(findings)
    finding_ids = [finding_id for finding_id, _block in finding_blocks]
    no_findings_markers = [
        "No confirmed vulnerabilities found",
        "No vulnerabilities found",
        "No findings",
    ]
    has_no_findings_marker = any(marker.lower() in findings.lower() for marker in no_findings_markers)
    if not finding_ids and not has_no_findings_marker:
        raise WorkflowFunctionError(
            f"{artifact} Findings must include at least one '### VULN-001 - ...' finding or explicitly state 'No confirmed vulnerabilities found'."
        )

    if finding_ids:
        if finding_ids[0] != "VULN-001":
            raise WorkflowFunctionError(f"{artifact} findings must start with VULN-001.")
        duplicate_ids = sorted({item for item in finding_ids if finding_ids.count(item) > 1})
        if duplicate_ids:
            raise WorkflowFunctionError(f"{artifact} has duplicate finding IDs: {', '.join(duplicate_ids)}")

        for expected_index, finding_id in enumerate(finding_ids, start=1):
            expected_id = f"VULN-{expected_index:03d}"
            if finding_id != expected_id:
                raise WorkflowFunctionError(
                    f"{artifact} finding IDs must be sequential. Expected {expected_id}, got {finding_id}."
                )

        for finding_id, block in finding_blocks:
            severity = _require_field_in_block(artifact, finding_id, block, "Severity")
            if severity not in valid_severities:
                raise WorkflowFunctionError(
                    f"{artifact} {finding_id} has invalid Severity '{severity}'. Use Critical, High, Medium, Low, or Info."
                )

            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence")
            if confidence not in valid_confidences:
                raise WorkflowFunctionError(
                    f"{artifact} {finding_id} has invalid Confidence '{confidence}'. Use High, Medium, or Low."
                )

            evidence = _require_field_in_block(artifact, finding_id, block, "Evidence")
            evidence_lower = evidence.lower()
            evidence_has_location = any(token in evidence for token in ["/", "\\", ".py", ".js", ".ts", ".java", ".cs", ".vb", ".yml", ".yaml", ".json", ".xml", ".properties", ":"])
            evidence_is_inferred = "inferred" in evidence_lower or "推測" in evidence or "推論" in evidence
            if not evidence_has_location and not evidence_is_inferred:
                raise WorkflowFunctionError(
                    f"{artifact} {finding_id} Evidence must include a file/path/function/config reference, or explicitly say it is inferred."
                )

            _require_field_in_block(artifact, finding_id, block, "Impact")
            _require_field_in_block(artifact, finding_id, block, "Recommendation")

    risk_matrix = _markdown_section_body(text, "Risk Matrix")
    if not risk_matrix:
        raise WorkflowFunctionError(f"{artifact} Risk Matrix section must not be empty.")
    risk_matrix_header = "| ID | Severity | Confidence | Area | Evidence Summary | Status |"
    if risk_matrix_header not in risk_matrix:
        raise WorkflowFunctionError(
            f"{artifact} Risk Matrix must include columns: ID, Severity, Confidence, Area, Evidence Summary, Status."
        )
    if finding_ids:
        missing = [finding_id for finding_id in finding_ids if finding_id not in risk_matrix]
        if missing:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix missing finding IDs: {', '.join(missing)}")
        for finding_id, block in finding_blocks:
            severity = _require_field_in_block(artifact, finding_id, block, "Severity")
            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence")
            matching_rows = [line for line in risk_matrix.splitlines() if f"| {finding_id} |" in line]
            if not matching_rows:
                raise WorkflowFunctionError(f"{artifact} Risk Matrix missing row for {finding_id}.")
            row = matching_rows[0]
            if f"| {severity} |" not in row or f"| {confidence} |" not in row:
                raise WorkflowFunctionError(
                    f"{artifact} Risk Matrix row for {finding_id} must repeat the finding Severity and Confidence."
                )
    elif not has_no_findings_marker and "No confirmed vulnerabilities found" not in risk_matrix:
        raise WorkflowFunctionError(f"{artifact} Risk Matrix must state 'No confirmed vulnerabilities found' when there are no findings.")


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
    "validate_security_report": validate_security_report,
}
