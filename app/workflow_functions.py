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
            "id": "collect_security_context",
            "label": "Collect Security Context",
            "description": "Collect bounded source/config snippets into output/security-context.md for security scanning.",
        },
        {
            "id": "combine_security_candidates",
            "label": "Combine Security Candidates",
            "description": "Merge same-task multi-agent security candidate files, deduplicate evidence, compute consensus confidence, and write output/security-findings.md.",
        },
        {
            "id": "validate_security_report",
            "label": "Validate Security Report",
            "description": "Check output/security-report.md contains required findings, source finding IDs, severity, confidence, evidence, and risk matrix format.",
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
        {"id": "security_context", "label": "Security Context", "description": "Content of output/security-context.md.", "sample": "# Security Scan Context"},
        {"id": "security_candidates", "label": "Security Candidates", "description": "Multi-agent candidate files such as security-candidates-auth-config.md.", "sample": "## CAND-001"},
        {"id": "security_findings", "label": "Security Findings", "description": "Python-combined normalized findings from output/security-findings.md.", "sample": "## SEC-001"},
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



SECURITY_CONTEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".cs", ".vb", ".go", ".rs", ".php", ".rb",
    ".yml", ".yaml", ".json", ".xml", ".properties", ".ini", ".toml", ".env", ".config", ".conf",
    ".sql", ".sh", ".ps1", ".bat", ".cmd", ".dockerfile",
}

SECURITY_CONTEXT_SKIP_DIRS = {
    ".git", ".qwen-workflow", "node_modules", "vendor", "venv", ".venv", "env", "__pycache__", ".pytest_cache",
    "dist", "build", "target", "bin", "obj", ".next", "coverage", ".idea", ".vscode",
}

SECURITY_KEYWORDS = [
    "password", "passwd", "secret", "token", "apikey", "api_key", "private_key", "jwt",
    "eval", "exec", "subprocess", "popen", "system(", "shell=True", "Runtime.getRuntime", "ProcessBuilder",
    "pickle", "yaml.load", "deserialize", "ObjectInputStream", "BinaryFormatter",
    "SELECT", "INSERT", "UPDATE", "DELETE", "execute(", "rawQuery", "createQuery", "SqlCommand",
    "open(", "readFile", "writeFile", "File(", "Path(", "send_file", "download", "upload",
    "http://", "requests.", "fetch(", "axios", "HttpClient", "RestTemplate", "WebClient",
    "cors", "csrf", "auth", "authorize", "permission", "role", "login", "session",
    "debug", "ssl", "verify=False", "trustAll", "AllowAnyOrigin",
]


def _is_security_context_file(path: Path) -> bool:
    name = path.name.lower()
    if name in {"dockerfile", "makefile", "pom.xml", "build.gradle", "package.json", "requirements.txt", "pyproject.toml", "go.mod", "cargo.toml", ".env", ".env.example"}:
        return True
    return path.suffix.lower() in SECURITY_CONTEXT_EXTENSIONS


def _safe_read_limited(path: Path, max_bytes: int) -> tuple[str, bool]:
    data = path.read_bytes()[: max_bytes + 1]
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    try:
        return data.decode("utf-8"), truncated
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), truncated


def _line_matches_security_keyword(line: str) -> bool:
    lowered = line.lower()
    return any(keyword.lower() in lowered for keyword in SECURITY_KEYWORDS)


def collect_security_context(ctx: WorkflowFunctionContext) -> None:
    project_dir = ctx.project_dir
    if not project_dir.exists() or not project_dir.is_dir():
        raise WorkflowFunctionError(f"Project path does not exist or is not a directory: {project_dir}")

    max_files = int(os.environ.get("SECURITY_CONTEXT_MAX_FILES", "80"))
    max_bytes_per_file = int(os.environ.get("SECURITY_CONTEXT_MAX_BYTES_PER_FILE", "12000"))
    max_total_chars = int(os.environ.get("SECURITY_CONTEXT_MAX_TOTAL_CHARS", "90000"))

    candidates: list[Path] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_dir)
        parts = set(relative.parts[:-1])
        if parts & SECURITY_CONTEXT_SKIP_DIRS:
            continue
        if not _is_security_context_file(path):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > 2_000_000:
            continue
        candidates.append(path)
        if len(candidates) >= max_files:
            break

    sections: list[str] = [
        "Status: DONE",
        "",
        "# Security Scan Context",
        "",
        f"Project path: {project_dir}",
        f"Files selected: {len(candidates)}",
        "",
        "## Selected Files",
    ]
    for path in candidates:
        try:
            relative = path.relative_to(project_dir).as_posix()
        except ValueError:
            relative = path.as_posix()
        sections.append(f"- {relative}")

    sections.extend(["", "## High-Signal Security Lines"])
    matched_any = False
    remaining = max_total_chars
    for path in candidates:
        if remaining <= 0:
            break
        relative = path.relative_to(project_dir).as_posix()
        try:
            content, truncated = _safe_read_limited(path, max_bytes_per_file)
        except OSError:
            continue
        matched_lines = []
        for number, line in enumerate(content.splitlines(), start=1):
            if _line_matches_security_keyword(line):
                matched_lines.append(f"{number}: {line[:220]}")
            if len(matched_lines) >= 25:
                break
        if matched_lines:
            matched_any = True
            block = f"\n### {relative}\n" + "\n".join(f"- {item}" for item in matched_lines)
            if truncated:
                block += "\n- [file content truncated for context size]"
            if len(block) > remaining:
                block = block[:remaining] + "\n[security context truncated]"
            sections.append(block)
            remaining -= len(block)
    if not matched_any:
        sections.append("- No high-signal keyword lines found in selected files.")

    sections.extend(["", "## File Content Samples"])
    for path in candidates:
        if remaining <= 0:
            break
        relative = path.relative_to(project_dir).as_posix()
        try:
            content, truncated = _safe_read_limited(path, min(max_bytes_per_file, 8000))
        except OSError:
            continue
        if not content.strip():
            continue
        content = content.strip()
        block = f"\n### {relative}\n{content}"
        if truncated:
            block += "\n[file content truncated]"
        if len(block) > remaining:
            block = block[:remaining] + "\n[security context truncated]"
        sections.append(block)
        remaining -= len(block)

    output_path = ctx.output_dir / "security-context.md"
    ctx.write_text(output_path, "\n".join(sections).strip() + "\n")


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


def _security_normalized_finding_blocks(text: str) -> list[tuple[str, str]]:
    import re

    matches = list(re.finditer(r"(?m)^##\s+(SEC-\d{3})\b.*$", text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[start:end].strip()))
    return blocks


def _require_field_in_block(artifact: str, finding_id: str, block: str, field: str) -> str:
    import re

    pattern = rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, block)
    if not match or not match.group(1).strip() or match.group(1).strip() in {"-", "N/A", "TBD", "Unknown"}:
        raise WorkflowFunctionError(f"{artifact} {finding_id} must include non-empty '{field}: ...'.")
    return match.group(1).strip()


def _optional_field_in_block(block: str, field: str) -> str:
    import re

    pattern = rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, block)
    return match.group(1).strip() if match else ""


def _markdown_table_rows(section_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "|" not in stripped[1:]:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and all(cell.replace("-", "").replace(":", "").strip() == "" for cell in cells):
            continue
        rows.append(cells)
    return rows


def _require_markdown_table(section_name: str, section_text: str, expected_header: list[str], artifact: str) -> list[list[str]]:
    rows = _markdown_table_rows(section_text)
    if not rows:
        raise WorkflowFunctionError(f"{artifact} {section_name} must contain a Markdown table.")
    header = rows[0]
    if header != expected_header:
        raise WorkflowFunctionError(
            f"{artifact} {section_name} table must use columns: {', '.join(expected_header)}."
        )
    data_rows = rows[1:]
    if not data_rows:
        raise WorkflowFunctionError(f"{artifact} {section_name} table must contain at least one data row.")
    for index, row in enumerate(data_rows, start=1):
        if len(row) != len(expected_header):
            raise WorkflowFunctionError(
                f"{artifact} {section_name} row {index} must have {len(expected_header)} columns, got {len(row)}."
            )
    return data_rows


def _security_evidence_has_location(evidence: str) -> bool:
    lower = evidence.lower()
    if "inferred" in lower or "推測" in evidence or "推論" in evidence:
        return True
    tokens = [
        "/", "\\", ":", ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".vb",
        ".go", ".php", ".rb", ".yml", ".yaml", ".json", ".xml", ".properties", ".env",
    ]
    return any(token in evidence for token in tokens)


def _security_field_value_rank(value: str, values: list[str], default: str) -> int:
    normalized = (value or "").strip().title()
    try:
        return values.index(normalized)
    except ValueError:
        return values.index(default)


def _security_best_severity(values: list[str]) -> str:
    order = ["Critical", "High", "Medium", "Low", "Info"]
    ranked = sorted(values or ["Info"], key=lambda item: _security_field_value_rank(item, order, "Info"))
    return ranked[0]


def _security_consensus_confidence(confidences: list[str], evidence: str, consensus_count: int) -> str:
    order = ["High", "Medium", "Low"]
    best = sorted(confidences or ["Low"], key=lambda item: _security_field_value_rank(item, order, "Low"))[0]
    has_location = _security_evidence_has_location(evidence)
    if consensus_count >= 2 and has_location and best in {"High", "Medium"}:
        return "High"
    if has_location and best in {"High", "Medium"}:
        return "Medium"
    return "Low"


def _security_candidate_key(candidate: dict[str, str]) -> str:
    import re

    evidence = candidate.get("Evidence") or ""
    file_value = candidate.get("File") or candidate.get("Location") or ""
    area = candidate.get("Area") or ""
    title = candidate.get("Title") or ""
    normalized = f"{file_value}|{area}|{evidence or title}".lower()
    normalized = re.sub(r"\bline\s*\d+\b", "line", normalized)
    normalized = re.sub(r"\d+", "#", normalized)
    normalized = re.sub(r"[^a-z0-9_./\\:#-]+", " ", normalized)
    return " ".join(normalized.split())[:220]


def _parse_security_candidates(artifact_name: str, text: str) -> list[dict[str, str]]:
    import re

    matches = list(re.finditer(r"(?m)^###+\s+(CAND-\d{3})\b\s*-?\s*(.*)$", text))
    candidates: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        item: dict[str, str] = {
            "Candidate ID": match.group(1),
            "Title": match.group(2).strip() or match.group(1),
            "Source Artifact": artifact_name,
            "Raw Block": block,
        }
        for field in [
            "Area", "File", "Location", "Function/Class", "Evidence", "Severity", "Severity Guess",
            "Confidence", "Confidence Guess", "Status", "Reason", "Impact", "Recommendation",
        ]:
            value = _optional_field_in_block(block, field)
            if value:
                item[field] = value
        if "Severity" not in item and "Severity Guess" in item:
            item["Severity"] = item["Severity Guess"]
        if "Confidence" not in item and "Confidence Guess" in item:
            item["Confidence"] = item["Confidence Guess"]
        if "Location" not in item and "File" in item:
            item["Location"] = item["File"]
        candidates.append(item)
    return candidates


def combine_security_candidates(ctx: WorkflowFunctionContext) -> None:
    """Merge multiple AI-generated security candidate artifacts into stable normalized findings."""
    candidate_files = sorted(path.name for path in ctx.output_dir.glob("security-candidates-agent-*.md"))
    if not candidate_files:
        raise WorkflowFunctionError("No security-candidates-agent-*.md artifacts found to combine.")
    valid_severities = {"Critical", "High", "Medium", "Low", "Info"}
    valid_confidences = {"High", "Medium", "Low"}
    accepted_statuses = {"Confirmed", "Likely", "Needs Review", "Hardening", "Candidate", "Risk"}
    rejected_statuses = {"False Positive", "Not Applicable", "No Finding"}

    all_candidates: list[dict[str, str]] = []
    missing_files: list[str] = []
    for name in candidate_files:
        path = ctx.output_dir / name
        text = ctx.read_text(path)
        if not text.strip():
            missing_files.append(name)
            continue
        all_candidates.extend(_parse_security_candidates(name, text))

    if missing_files:
        raise WorkflowFunctionError(f"Missing security candidate artifact(s): {', '.join(missing_files)}")

    if not all_candidates:
        raise WorkflowFunctionError("No CAND-### entries were found in multi-agent security candidate artifacts.")

    grouped: dict[str, list[dict[str, str]]] = {}
    rejected: list[dict[str, str]] = []
    for candidate in all_candidates:
        status = (candidate.get("Status") or "Candidate").strip().title()
        if status in rejected_statuses:
            rejected.append(candidate)
            continue
        evidence = candidate.get("Evidence") or ""
        severity = (candidate.get("Severity") or "Info").strip().title()
        confidence = (candidate.get("Confidence") or "Low").strip().title()
        if severity not in valid_severities or confidence not in valid_confidences:
            rejected.append(candidate)
            continue
        if not evidence or evidence in {"-", "N/A", "Unknown", "TBD"}:
            rejected.append(candidate)
            continue
        if status not in accepted_statuses:
            candidate["Status"] = "Needs Review"
        key = _security_candidate_key(candidate)
        grouped.setdefault(key, []).append(candidate)

    lines: list[str] = [
        "Status: DONE",
        "",
        "# Security Findings",
        "",
        "## Combination Summary",
        f"- Candidate artifacts read: {', '.join(candidate_files)}",
        f"- Raw candidates: {len(all_candidates)}",
        f"- Accepted groups: {len(grouped)}",
        f"- Rejected candidates: {len(rejected)}",
        "- Confidence merge rule: repeated same-task agents + concrete evidence raise confidence; weak or inferred evidence remains Low.",
        "",
        "## Accepted Findings",
    ]

    if not grouped:
        lines.extend([
            "- No accepted security findings after Python filtering and deduplication.",
            "",
            "## Rejected / Low Evidence Candidates",
        ])
    else:
        for index, (_key, items) in enumerate(sorted(grouped.items(), key=lambda kv: kv[0]), start=1):
            sec_id = f"SEC-{index:03d}"
            title = next((item.get("Title") for item in items if item.get("Title")), "Security finding")
            area = next((item.get("Area") for item in items if item.get("Area")), "General")
            evidence = next((item.get("Evidence") for item in items if _security_evidence_has_location(item.get("Evidence", ""))), items[0].get("Evidence", ""))
            severity = _security_best_severity([item.get("Severity", "Info") for item in items])
            confidence = _security_consensus_confidence([item.get("Confidence", "Low") for item in items], evidence, len(items))
            status = "Likely" if confidence in {"High", "Medium"} and severity != "Info" else "Needs Review"
            if severity == "Info":
                status = "Hardening"
            source_ids = [f"{item.get('Source Artifact')}:{item.get('Candidate ID')}" for item in items]
            reason = next((item.get("Reason") for item in items if item.get("Reason")), "Consolidated by Python from multi-agent candidates.")
            impact = next((item.get("Impact") for item in items if item.get("Impact")), "Potential security weakness depending on runtime exposure and input trust boundary.")
            recommendation = next((item.get("Recommendation") for item in items if item.get("Recommendation")), "Review the referenced code/config and apply the least-risk secure pattern.")
            lines.extend([
                f"## {sec_id} - {title}",
                f"- Source Candidate IDs: {', '.join(source_ids)}",
                f"- Area: {area}",
                f"- Severity: {severity}",
                f"- Confidence: {confidence}",
                f"- Consensus Count: {len(items)}",
                f"- Status: {status}",
                f"- Evidence: {evidence}",
                f"- Reason: {reason}",
                f"- Impact: {impact}",
                f"- Recommendation: {recommendation}",
                "",
            ])
        lines.append("## Rejected / Low Evidence Candidates")

    if not rejected:
        lines.append("- None.")
    else:
        for item in rejected[:50]:
            lines.append(
                f"- {item.get('Source Artifact')}:{item.get('Candidate ID')} | "
                f"Status={item.get('Status', 'Rejected')} | "
                f"Severity={item.get('Severity', 'Unknown')} | "
                f"Confidence={item.get('Confidence', 'Unknown')} | "
                f"Evidence={item.get('Evidence', '').strip()[:160] or 'missing'}"
            )

    ctx.write_text(ctx.output_dir / "security-findings.md", "\n".join(lines).rstrip() + "\n")


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
        "Security Checklist",
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

    security_findings_text = ctx.read_text(ctx.output_dir / "security-findings.md")
    normalized_findings = _security_normalized_finding_blocks(security_findings_text)
    normalized_ids = [finding_id for finding_id, _block in normalized_findings]

    checklist = _markdown_section_body(text, "Security Checklist")
    checklist_rows = _require_markdown_table(
        "Security Checklist",
        checklist,
        ["Check", "Status", "Evidence", "Notes"],
        artifact,
    )
    if len(checklist_rows) < 8:
        raise WorkflowFunctionError(f"{artifact} Security Checklist must contain at least 8 reviewed security categories.")
    allowed_check_statuses = {"Reviewed", "Finding", "Risk", "Not applicable", "Limited"}
    for index, row in enumerate(checklist_rows, start=1):
        check, status, evidence, _notes = row
        if not check:
            raise WorkflowFunctionError(f"{artifact} Security Checklist row {index} has empty Check.")
        if status not in allowed_check_statuses:
            raise WorkflowFunctionError(
                f"{artifact} Security Checklist row {index} has invalid Status '{status}'. Use Reviewed, Finding, Risk, Not applicable, or Limited."
            )
        if not evidence or evidence in {"-", "N/A", "Unknown"}:
            raise WorkflowFunctionError(f"{artifact} Security Checklist row {index} must include concrete evidence or limitation.")

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

    if normalized_ids and not finding_ids:
        raise WorkflowFunctionError(
            f"{artifact} must convert every accepted SEC finding from security-findings.md into VULN findings. Missing: {', '.join(normalized_ids)}"
        )

    mapped_source_ids: list[str] = []
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
            source_id = _require_field_in_block(artifact, finding_id, block, "Source Finding ID")
            if not source_id.startswith("SEC-"):
                raise WorkflowFunctionError(f"{artifact} {finding_id} Source Finding ID must be SEC-###.")
            mapped_source_ids.append(source_id)

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
            if not _security_evidence_has_location(evidence):
                raise WorkflowFunctionError(
                    f"{artifact} {finding_id} Evidence must include a file/path/function/config reference, or explicitly say it is inferred."
                )

            _require_field_in_block(artifact, finding_id, block, "Impact")
            _require_field_in_block(artifact, finding_id, block, "Recommendation")

    missing_source_ids = [source_id for source_id in normalized_ids if source_id not in mapped_source_ids]
    if missing_source_ids:
        raise WorkflowFunctionError(
            f"{artifact} Findings missing Source Finding ID(s) from security-findings.md: {', '.join(missing_source_ids)}"
        )

    risk_matrix = _markdown_section_body(text, "Risk Matrix")
    if not risk_matrix:
        raise WorkflowFunctionError(f"{artifact} Risk Matrix section must not be empty.")
    risk_matrix_rows = _require_markdown_table(
        "Risk Matrix",
        risk_matrix,
        ["ID", "Source Finding ID", "Severity", "Confidence", "Area", "Evidence Summary", "Status"],
        artifact,
    )
    for index, row in enumerate(risk_matrix_rows, start=1):
        if row[0] != "NONE" and not row[0].startswith("VULN-"):
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} ID must be VULN-### or NONE.")
        if row[1] != "NONE" and not row[1].startswith("SEC-"):
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} Source Finding ID must be SEC-### or NONE.")
        if row[2] not in valid_severities:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} has invalid Severity '{row[2]}'.")
        if row[3] not in valid_confidences:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} has invalid Confidence '{row[3]}'.")
        if not row[4] or not row[5] or not row[6]:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} must fill Area, Evidence Summary, and Status.")
    if finding_ids:
        missing = [finding_id for finding_id in finding_ids if finding_id not in risk_matrix]
        if missing:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix missing finding IDs: {', '.join(missing)}")
        for finding_id, block in finding_blocks:
            source_id = _require_field_in_block(artifact, finding_id, block, "Source Finding ID")
            severity = _require_field_in_block(artifact, finding_id, block, "Severity")
            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence")
            matching_rows = [line for line in risk_matrix.splitlines() if f"| {finding_id} |" in line]
            if not matching_rows:
                raise WorkflowFunctionError(f"{artifact} Risk Matrix missing row for {finding_id}.")
            row = matching_rows[0]
            if f"| {source_id} |" not in row or f"| {severity} |" not in row or f"| {confidence} |" not in row:
                raise WorkflowFunctionError(
                    f"{artifact} Risk Matrix row for {finding_id} must repeat Source Finding ID, Severity, and Confidence."
                )
    else:
        if normalized_ids:
            raise WorkflowFunctionError(f"{artifact} cannot use no-finding output when security-findings.md has accepted findings.")
        if not has_no_findings_marker and "No confirmed vulnerabilities found" not in risk_matrix:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix must state 'No confirmed vulnerabilities found' when there are no findings.")
        for row in risk_matrix_rows:
            row_text = " | ".join(row)
            if "No confirmed vulnerabilities found" in row_text:
                if row[0] != "NONE" or row[1] != "NONE":
                    raise WorkflowFunctionError(
                        f"{artifact} Risk Matrix no-finding row must use ID 'NONE' and Source Finding ID 'NONE'."
                    )
                if row[2] not in {"Info", "Low"}:
                    raise WorkflowFunctionError(f"{artifact} Risk Matrix no-finding row Severity must be Info or Low.")
                if row[3] not in valid_confidences:
                    raise WorkflowFunctionError(f"{artifact} Risk Matrix no-finding row Confidence must be High, Medium, or Low.")

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
    "collect_security_context": collect_security_context,
    "combine_security_candidates": combine_security_candidates,
    "validate_spec": validate_spec,
    "validate_todo": validate_todo,
    "require_status_pass": require_status_pass,
    "run_pytest": run_pytest,
    "validate_security_report": validate_security_report,
}
