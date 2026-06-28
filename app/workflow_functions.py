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


from app.workflow_function_catalog import AVAILABLE_WORKFLOW_FUNCTIONS
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
    ".git", ".hg", ".svn", ".vs", ".idea", ".vscode", ".qwen-workflow",
    "node_modules", "vendor", "bower_components",
    "venv", ".venv", "env", ".envdir",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
    "dist", "build", "target", "bin", "obj", "out", ".next", ".nuxt", ".svelte-kit",
    "coverage", ".coverage", "htmlcov",
    ".gradle", ".mvn", ".parcel-cache", ".turbo", ".cache",
    "logs", "log", "tmp", "temp",
}

SECURITY_CONTEXT_SKIP_FILE_NAMES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".coverage", "coverage.xml",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
}

SECURITY_CONTEXT_SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war", ".ear",
    ".dll", ".exe", ".pdb", ".so", ".dylib", ".o", ".obj",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".log", ".tmp", ".cache",
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
    if name in SECURITY_CONTEXT_SKIP_FILE_NAMES:
        return False
    if path.suffix.lower() in SECURITY_CONTEXT_SKIP_SUFFIXES:
        return False
    if name in {"dockerfile", "makefile", "pom.xml", "build.gradle", "package.json", "requirements.txt", "pyproject.toml", "go.mod", "cargo.toml", ".env", ".env.example"}:
        return True
    return path.suffix.lower() in SECURITY_CONTEXT_EXTENSIONS


def _is_under_security_excluded_path(relative: Path) -> bool:
    return any(part in SECURITY_CONTEXT_SKIP_DIRS for part in relative.parts[:-1])


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


def _security_excerpt_for_file(path: Path, project_dir: Path, max_chars: int) -> str:
    text, truncated = _safe_read_limited(path, max_chars)
    lines = text.splitlines()
    matched_indexes = [index for index, line in enumerate(lines) if _line_matches_security_keyword(line)]
    if not matched_indexes:
        matched_indexes = list(range(min(len(lines), 20)))
    selected: list[int] = []
    for index in matched_indexes[:12]:
        selected.extend(range(max(0, index - 2), min(len(lines), index + 3)))
    if not selected:
        return ""
    unique_indexes = sorted(set(selected))
    rel = path.relative_to(project_dir).as_posix()
    output = [f"### {rel}", "```text"]
    for index in unique_indexes:
        line = lines[index].rstrip()
        if len(line) > 240:
            line = line[:237] + "..."
        output.append(f"{index + 1}: {line}")
    if truncated:
        output.append("[File read truncated]")
    output.append("```")
    return "\n".join(output)


def collect_security_context(ctx: WorkflowFunctionContext) -> None:
    """Write bounded security scan context with inventory and relevant excerpts."""
    project_dir = ctx.project_dir
    if not project_dir.exists() or not project_dir.is_dir():
        raise WorkflowFunctionError(f"Project path does not exist or is not a directory: {project_dir}")

    max_inventory = int(os.environ.get("SECURITY_SCOPE_MAX_FILES", "300"))
    included_count = 0
    excluded_dir_count = 0
    excluded_file_count = 0
    inventory: list[str] = []
    excerpt_candidates: list[tuple[int, str, Path]] = []
    extension_counts: dict[str, int] = {}
    max_excerpt_files = int(os.environ.get("SECURITY_SCOPE_MAX_EXCERPT_FILES", "40"))
    max_file_bytes = int(os.environ.get("SECURITY_SCOPE_MAX_FILE_BYTES", "24000"))
    max_total_excerpt_chars = int(os.environ.get("SECURITY_SCOPE_MAX_EXCERPT_CHARS", "60000"))

    for path in sorted(project_dir.rglob("*")):
        try:
            relative = path.relative_to(project_dir)
        except ValueError:
            continue
        if path.is_dir():
            if relative.name in SECURITY_CONTEXT_SKIP_DIRS or _is_under_security_excluded_path(relative / "dummy"):
                excluded_dir_count += 1
            continue
        if not path.is_file():
            continue
        if _is_under_security_excluded_path(relative):
            excluded_file_count += 1
            continue
        if path.name.lower() in SECURITY_CONTEXT_SKIP_FILE_NAMES or path.suffix.lower() in SECURITY_CONTEXT_SKIP_SUFFIXES:
            excluded_file_count += 1
            continue
        included_count += 1
        suffix = path.suffix.lower() or "[no extension]"
        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1
        if len(inventory) < max_inventory:
            inventory.append(relative.as_posix())
        score = 0
        rel_text = relative.as_posix().lower()
        if any(keyword.lower() in rel_text for keyword in SECURITY_KEYWORDS):
            score += 3
        try:
            sample, _truncated = _safe_read_limited(path, min(max_file_bytes, 12000))
            score += sum(1 for line in sample.splitlines() if _line_matches_security_keyword(line))
        except OSError:
            sample = ""
        if score > 0:
            excerpt_candidates.append((score, relative.as_posix(), path))

    extension_summary = sorted(extension_counts.items(), key=lambda item: (-item[1], item[0]))[:30]
    excerpt_candidates.sort(key=lambda item: (-item[0], item[1]))
    excerpt_blocks: list[str] = []
    excerpt_chars = 0
    for _score, _relative, path in excerpt_candidates[:max_excerpt_files]:
        try:
            block = _security_excerpt_for_file(path, project_dir, max_file_bytes)
        except OSError:
            continue
        if not block.strip():
            continue
        if excerpt_chars + len(block) > max_total_excerpt_chars:
            break
        excerpt_blocks.append(block)
        excerpt_chars += len(block)

    sections: list[str] = [
        "Status: DONE",
        "",
        "# Security Scan Scope",
        "",
        f"Project path: {project_dir}",
        "Source content embedded: Bounded security-relevant excerpts",
        "Agent input mode: Use Project Path plus the bounded excerpts below. If direct file tools are unavailable, base candidates only on these excerpts and state limitations.",
        f"Included file count: {included_count}",
        f"Excluded directory count: {excluded_dir_count}",
        f"Excluded file count: {excluded_file_count}",
        f"Excerpt file count: {len(excerpt_blocks)}",
        "",
        "## Exclusion Rules",
        "- Excluded directories: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_DIRS)),
        "- Excluded file names: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_FILE_NAMES)),
        "- Excluded suffixes: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_SUFFIXES)),
        "",
        "## Extension Summary",
    ]
    if extension_summary:
        sections.extend(f"- {suffix}: {count}" for suffix, count in extension_summary)
    else:
        sections.append("- No scannable files found after exclusions.")

    sections.extend([
        "",
        "## File Inventory Preview",
        f"Showing up to {max_inventory} relative paths.",
    ])
    if inventory:
        sections.extend(f"- {item}" for item in inventory)
        if included_count > len(inventory):
            sections.append(f"- ... {included_count - len(inventory)} more files omitted from preview")
    else:
        sections.append("- No scannable files found after exclusions.")

    sections.extend([
        "",
        "## Security Relevant Excerpts",
    ])
    if excerpt_blocks:
        sections.extend(excerpt_blocks)
    else:
        sections.append("Limitation: no security-keyword excerpts were collected from scannable files.")

    sections.extend([
        "",
        "## Notes For Agents",
        "- Use Project Path for direct inspection when available.",
        "- If direct inspection is unavailable, use Security Relevant Excerpts as bounded evidence and state that limitation.",
        "- Real vulnerability evidence should cite project file path, line/function/class/config, and observed behavior.",
    ])

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
    if not match or _security_is_placeholder_text(match.group(1)):
        raise WorkflowFunctionError(f"{artifact} {finding_id} must include non-empty '{field}: ...'.")
    return match.group(1).strip()


def _optional_field_in_block(block: str, field: str) -> str:
    import re

    pattern = rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, block)
    return match.group(1).strip() if match else ""


def _split_markdown_table_line(line: str) -> list[str]:
    """Split a Markdown table line while tolerating escaped pipes and inline code pipes.

    AI reports often include code snippets like `a | b` in Evidence cells. A raw
    split("|") treats those snippets as extra columns and causes noisy retries.
    This parser keeps pipes inside backtick code spans or escaped as \\| inside
    the current cell.
    """
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    in_code = False
    escaped = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            current.append(char)
            continue
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _markdown_table_rows(section_text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "|" not in stripped[1:]:
            continue
        cells = _split_markdown_table_line(stripped)
        if cells and all(cell.replace("-", "").replace(":", "").strip() == "" for cell in cells):
            continue
        rows.append(cells)
    return rows


def _coerce_markdown_table_row(row: list[str], expected_len: int) -> list[str]:
    if len(row) == expected_len:
        return row
    if len(row) > expected_len:
        # Keep the schema stable and join accidental extra cells into the last
        # free-text column. This commonly happens when Evidence/Notes contains
        # an unescaped pipe from source code or markdown.
        return row[: expected_len - 1] + [" | ".join(row[expected_len - 1:]).strip()]
    return row + [""] * (expected_len - len(row))


def _require_markdown_table(section_name: str, section_text: str, expected_header: list[str], artifact: str) -> list[list[str]]:
    rows = _markdown_table_rows(section_text)
    if not rows:
        raise WorkflowFunctionError(f"{artifact} {section_name} must contain a Markdown table.")
    header = _coerce_markdown_table_row(rows[0], len(expected_header))
    if header != expected_header:
        raise WorkflowFunctionError(
            f"{artifact} {section_name} table must use columns: {', '.join(expected_header)}."
        )
    data_rows = [_coerce_markdown_table_row(row, len(expected_header)) for row in rows[1:]]
    if not data_rows:
        raise WorkflowFunctionError(f"{artifact} {section_name} table must contain at least one data row.")
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




SECURITY_SCORE_THRESHOLDS = {
    "total": 75,
    "evidence": 18,
    "confidence": 12,
    "coverage": 12,
}

SECURITY_REPORT_SCORE_THRESHOLDS = {
    "total": 80,
    "evidence": 18,
    "confidence": 12,
    "coverage": 12,
    "source_mapping": 8,
}


def _security_score_artifact_name(artifact: str) -> str:
    path = Path(artifact)
    suffix = path.suffix or ".md"
    return f"{path.stem}-score{suffix}"


def _security_report_score_artifact_name(artifact: str = "security-report.md") -> str:
    path = Path(artifact)
    suffix = path.suffix or ".md"
    return f"{path.stem}-score{suffix}"


def _security_evidence_score_value(evidence: str, *, status: str = "") -> int:
    evidence = (evidence or "").strip()
    if not evidence or evidence in {"-", "N/A", "Unknown", "TBD"}:
        return 0
    lower = evidence.lower()
    has_location = _security_evidence_has_location(evidence)
    inferred = lower.startswith("inferred:") or "inferred" in lower or "推測" in evidence or "推論" in evidence
    has_line_or_symbol = any(token in evidence for token in [":", "#", "()", "function", "class", "config", "line", "Line"])
    has_code_signal = any(token in lower for token in ["uses ", "call", "execute", "decode", "open(", "eval", "exec", "shell", "password", "token", "secret", "query", "sql", "cors", "debug"])

    if status == "No Finding" and has_location:
        return 24
    if has_location and has_line_or_symbol and has_code_signal and not inferred:
        return 30
    if has_location and (has_line_or_symbol or has_code_signal) and not inferred:
        return 26
    if has_location and not inferred:
        return 22
    if inferred and has_location:
        return 16
    if inferred:
        return 12
    return 6


def _security_parse_confidence_score(value: str) -> int | None:
    import re

    raw = (value or "").strip()
    if not re.fullmatch(r"\d{1,3}", raw):
        return None
    score = int(raw)
    if score < 0 or score > 100:
        return None
    return score


def _security_require_confidence_score(value: str, artifact: str, target: str) -> int:
    score = _security_parse_confidence_score(value)
    if score is None:
        raise WorkflowFunctionError(
            f"{artifact} {target} has invalid Confidence Score '{value}'. Use an integer from 0 to 100."
        )
    return score

SECURITY_VALID_STATUSES = {"Confirmed", "Likely", "Needs Review", "Hardening", "False Positive", "Not Applicable", "No Finding"}
SECURITY_STATUS_ORDER = ["False Positive", "Not Applicable", "Needs Review", "No Finding", "Confirmed", "Hardening", "Likely"]
SECURITY_CONFIDENCE_WORD_SCORES = {
    "very high": 90,
    "high": 85,
    "medium": 65,
    "moderate": 65,
    "low": 35,
    "very low": 20,
}


def _security_clean_enum_value(value: str) -> str:
    """Remove common Markdown decoration around enum-like values."""
    import re

    cleaned = (value or "").strip()
    cleaned = cleaned.strip("`*_ ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _security_normalize_check_status_value(value: str) -> str | None:
    """Normalize checklist table status values without burning retries."""
    import re

    cleaned = _security_clean_enum_value(value)
    if not cleaned:
        return None
    lowered = cleaned.lower().replace("_", " ").replace("-", " ")
    lowered = re.sub(r"\s+", " ", lowered).strip()
    mapping = {
        "reviewed": "Reviewed",
        "review": "Reviewed",
        "reviewing": "Reviewed",
        "checked": "Reviewed",
        "checked reviewed": "Reviewed",
        "finding": "Finding",
        "findings": "Finding",
        "found": "Finding",
        "risk": "Risk",
        "risky": "Risk",
        "needs review": "Limited",
        "need review": "Limited",
        "limited": "Limited",
        "limitation": "Limited",
        "partial": "Limited",
        "not applicable": "Not applicable",
        "not applicable reviewed": "Not applicable",
        "not appicable": "Not applicable",
        "n/a": "Not applicable",
        "na": "Not applicable",
        "no finding": "Reviewed",
        "no findings": "Reviewed",
        "none": "Reviewed",
    }
    if lowered in mapping:
        return mapping[lowered]
    if "not applicable" in lowered or lowered in {"n a", "n/a"}:
        return "Not applicable"
    if "need" in lowered and "review" in lowered:
        return "Limited"
    if "review" in lowered:
        return "Reviewed"
    if "finding" in lowered or "found" in lowered:
        return "Finding"
    if "risk" in lowered:
        return "Risk"
    if "limit" in lowered or "partial" in lowered:
        return "Limited"
    return None


def _security_normalize_severity_value(value: str) -> str | None:
    """Normalize severity enum values and repair copied enum placeholders."""
    cleaned = _security_clean_enum_value(value)
    if not cleaned:
        return None
    valid = ["Critical", "High", "Medium", "Low", "Info"]
    if cleaned in valid:
        return cleaned
    lowered = cleaned.lower()
    # Model sometimes copies the enum instruction literally. Use a neutral
    # severity so scoring can continue and quality checks can handle the finding.
    if "|" in cleaned and all(token.lower() in lowered for token in ["critical", "high", "medium", "low", "info"]):
        return "Medium"
    for severity in valid:
        if lowered == severity.lower():
            return severity
    for severity in valid:
        if severity.lower() in lowered:
            return severity
    return None


def _security_normalize_status_value(value: str) -> str | None:
    import re

    raw = _security_clean_enum_value(value)
    if not raw:
        return None
    compact = re.sub(r"\s+", " ", raw).strip()
    if compact in SECURITY_VALID_STATUSES:
        return compact
    lowered = compact.lower()
    for status in SECURITY_STATUS_ORDER:
        status_lower = status.lower()
        if lowered == status_lower:
            return status
        if lowered.startswith(status_lower + ":") or lowered.startswith(status_lower + " -") or lowered.startswith(status_lower + " ("):
            return status
        if re.search(rf"\b{re.escape(status_lower)}\b", lowered):
            return status
    return None


def _security_extract_confidence_score_from_text(*values: str) -> int | None:
    import re

    combined = " ".join((value or "") for value in values).strip()
    if not combined:
        return None
    numeric = re.search(r"(?<!\d)(100|[1-9]?\d)(?:\s*%|\s*/\s*100)?(?!\d)", combined)
    if numeric:
        score = int(numeric.group(1))
        if 0 <= score <= 100:
            return score
    lowered = combined.lower()
    # Check longer phrases first so "very high" is not reduced to "high".
    for word, score in sorted(SECURITY_CONFIDENCE_WORD_SCORES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return score
    return None


def _security_normalize_status_and_confidence(status: str, confidence: str) -> tuple[str | None, str | None, list[str]]:
    notes: list[str] = []
    normalized_status = _security_normalize_status_value(status)
    if normalized_status and normalized_status != (status or "").strip():
        notes.append(f"normalized Status '{status}' -> '{normalized_status}'")

    parsed_confidence = _security_parse_confidence_score(confidence)
    if parsed_confidence is not None:
        return normalized_status, str(parsed_confidence), notes

    extracted = _security_extract_confidence_score_from_text(confidence, status)
    if extracted is not None:
        notes.append(f"normalized Confidence Score '{confidence or status}' -> '{extracted}'")
        return normalized_status, str(extracted), notes

    return normalized_status, None, notes


def _replace_or_insert_markdown_field(block: str, field: str, value: str, *, after_fields: list[str] | None = None) -> str:
    import re

    replacement = f"- {field}: {value}"
    pattern = rf"(?im)^\s*[-*]?\s*{re.escape(field)}\s*:\s*.*$"
    if re.search(pattern, block):
        return re.sub(pattern, replacement, block, count=1)

    lines = block.splitlines()
    insert_at = 1 if lines else 0
    after_fields = after_fields or []
    for index, line in enumerate(lines):
        for after_field in after_fields:
            if re.match(rf"(?i)^\s*[-*]?\s*{re.escape(after_field)}\s*:\s*", line):
                insert_at = index + 1
    lines.insert(insert_at, replacement)
    return "\n".join(lines)


def _replace_markdown_section_body(text: str, section: str, body: str) -> str:
    marker = f"## {section}"
    start = text.find(marker)
    if start < 0:
        return text
    body_start = text.find("\n", start)
    if body_start < 0:
        return text
    body_start += 1
    next_section = text.find("\n## ", body_start)
    if next_section < 0:
        next_section = len(text)
        suffix = ""
    else:
        suffix = text[next_section:]
    return text[:body_start] + body.rstrip() + "\n" + suffix


def _security_confidence_guess_from_score(score: int | None) -> str:
    if score is None:
        return "Medium"
    if score >= 80:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def _security_normalize_confidence_guess_value(value: str) -> str | None:
    raw = (value or "").strip().replace("**", "")
    if not raw:
        return None
    parsed = _security_parse_confidence_score(raw)
    if parsed is not None:
        return _security_confidence_guess_from_score(parsed)
    lowered = raw.lower()
    if "very high" in lowered or "high" in lowered:
        return "High"
    if "moderate" in lowered or "medium" in lowered:
        return "Medium"
    if "very low" in lowered or "low" in lowered:
        return "Low"
    return None


def _security_is_placeholder_text(value: str) -> bool:
    cleaned = (value or "").strip().strip("`*_ <>[]()")
    lowered = cleaned.lower()
    if lowered in {"", "-", "_", "n/a", "na", "none", "unknown", "tbd", "not found"}:
        return True
    placeholder_tokens = [
        "short candidate title",
        "security area",
        "file path from project path",
        "function/class/config name",
        "file/path/function/config evidence",
        "why this is or is not a candidate",
        "risk impact",
        "defensive remediation",
        "example area",
        "path/to/file.ext",
        "brief scope based on project path",
    ]
    return any(token in lowered for token in placeholder_tokens)


def _security_is_limitation_text(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return any(token in lowered for token in [
        "limitation:", "not found", "not observed", "not identified", "not detected",
        "no concrete", "no evidence", "no related", "no relevant", "not applicable",
        "does not appear", "not present", "未發現", "未找到", "未識別", "不適用", "沒有"
    ])


def _security_limit_text(check: str, target: str = "evidence") -> str:
    base = (check or "this checklist item").strip() or "this checklist item"
    if target == "notes":
        return f"Limitation: no confirmed finding was identified for {base} in the scanned project path."
    return f"Limitation: no concrete file/config evidence identified for {base} in the scanned project path."


def _security_confidence_guess_score(value: str, evidence_score: int, *, status: str = "") -> int:
    guess = _security_normalize_confidence_guess_value(value)
    if status in {"No Finding", "Not Applicable", "False Positive"}:
        return 16 if guess in {"High", "Medium"} and evidence_score >= 12 else 10
    if guess == "High":
        return 18 if evidence_score >= 18 else 8
    if guess == "Medium":
        return 16 if evidence_score >= 12 else 10
    if guess == "Low":
        return 14 if evidence_score <= 18 else 10
    return 6


def _normalize_security_candidate_artifact_text(text: str) -> tuple[str, list[str]]:
    """Repair small AI formatting mistakes before strict scoring.

    This validator no longer trusts an AI-produced final Confidence Score.
    AI may provide only a qualitative AI Confidence Guess; Python computes the
    official numeric Confidence Score later during combine_security_candidates.
    """
    import re

    notes: list[str] = []
    result = text
    feedback_marker = "\nFailure feedback from previous retry attempts."
    if feedback_marker in result:
        result = result.split(feedback_marker, 1)[0].rstrip() + "\n"
        notes.append("removed trailing retry feedback copied into candidate artifact")

    checklist_section = _markdown_section_body(result, "Checklist Coverage")
    checklist_rows = _markdown_table_rows(checklist_section)
    if checklist_rows:
        header = _coerce_markdown_table_row(checklist_rows[0], 4)
        if header[:4] == ["Check", "Status", "Evidence", "Notes"]:
            normalized_rows = [["Check", "Status", "Evidence", "Notes"], ["---", "---", "---", "---"]]
            for row_index, row in enumerate(checklist_rows[1:], start=1):
                check, status, evidence, note_text = _coerce_markdown_table_row(row, 4)[:4]
                normalized_check_status = _security_normalize_check_status_value(status)
                if normalized_check_status and normalized_check_status != status:
                    notes.append(f"Checklist row {row_index}: normalized Status '{status}' -> '{normalized_check_status}'")
                    status = normalized_check_status
                elif not normalized_check_status:
                    notes.append(f"Checklist row {row_index}: normalized invalid Status '{status}' -> 'Limited'")
                    status = "Limited"
                if _security_is_placeholder_text(evidence):
                    evidence = _security_limit_text(check, "evidence")
                    notes.append(f"Checklist row {row_index}: replaced placeholder Evidence with limitation text")
                if _security_is_placeholder_text(note_text):
                    note_text = _security_limit_text(check, "notes")
                    notes.append(f"Checklist row {row_index}: replaced placeholder Notes with limitation text")
                normalized_rows.append([check, status, evidence, note_text])
            table_lines = ["| " + " | ".join(row) + " |" for row in normalized_rows]
            result = _replace_markdown_section_body(result, "Checklist Coverage", "\n".join(table_lines))

    # Some agents forget the explicit ## Candidates section and place CAND
    # blocks right after Candidate Index. Insert the missing section rather than
    # burning retries for a cosmetic heading omission.
    if "## Candidates" not in result:
        result, count = re.subn(r"(?m)^(###\s+CAND-\d{3}\b)", r"## Candidates\n\1", result, count=1)
        if count:
            notes.append("inserted missing ## Candidates section before first CAND block")

    candidate_index = _markdown_section_body(result, "Candidate Index")
    rows = _markdown_table_rows(candidate_index)
    if rows:
        header = _coerce_markdown_table_row(rows[0], max(len(rows[0]), 6))
        old_header = ["ID", "Severity", "Confidence Score", "Status", "Area", "Evidence Summary"]
        new_header = ["ID", "Severity", "AI Confidence Guess", "Status", "Area", "Evidence Summary"]
        if tuple(header[:6]) in {tuple(old_header), tuple(new_header)}:
            normalized_rows = [new_header, ["---", "---", "---", "---", "---", "---"]]
            for row in rows[1:]:
                row = _coerce_markdown_table_row(row, 6)
                candidate_id, severity, confidence_guess, status, area, evidence_summary = row[:6]
                normalized_severity = _security_normalize_severity_value(severity)
                if normalized_severity and normalized_severity != severity:
                    notes.append(f"{candidate_id}: normalized Severity '{severity}' -> '{normalized_severity}'")
                    severity = normalized_severity
                elif not normalized_severity:
                    notes.append(f"{candidate_id}: normalized invalid Severity '{severity}' -> 'Medium'")
                    severity = "Medium"
                normalized_status, _normalized_confidence, row_notes = _security_normalize_status_and_confidence(status, confidence_guess)
                if normalized_status:
                    status = normalized_status
                guess = _security_normalize_confidence_guess_value(confidence_guess) or "Medium"
                if guess != confidence_guess:
                    notes.append(f"{candidate_id}: normalized AI Confidence Guess '{confidence_guess}' -> '{guess}'")
                notes.extend(f"{candidate_id}: {note}" for note in row_notes if "Confidence Score" not in note)
                normalized_rows.append([candidate_id, severity, guess, status, area, evidence_summary])
            table_lines = ["| " + " | ".join(row) + " |" for row in normalized_rows]
            result = _replace_markdown_section_body(result, "Candidate Index", "\n".join(table_lines))

    matches = list(re.finditer(r"(?m)^###+\s+(CAND-\d{3})\b.*$", result))
    if not matches:
        return result, notes

    pieces: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(result)
        pieces.append(result[cursor:start])
        block = result[start:end]
        candidate_id = match.group(1)
        status_value = _optional_field_in_block(block, "Status")
        ai_guess_value = (
            _optional_field_in_block(block, "AI Confidence Guess")
            or _optional_field_in_block(block, "Confidence Guess")
            or _optional_field_in_block(block, "Confidence")
            or _optional_field_in_block(block, "Confidence Score")
        )
        normalized_status, _unused_numeric, block_notes = _security_normalize_status_and_confidence(status_value, ai_guess_value)
        severity_value = _optional_field_in_block(block, "Severity")
        normalized_severity = _security_normalize_severity_value(severity_value)
        if normalized_severity and normalized_severity != severity_value:
            block = _replace_or_insert_markdown_field(block, "Severity", normalized_severity, after_fields=["Exploitability Seen"])
            notes.append(f"{candidate_id}: normalized Severity '{severity_value}' -> '{normalized_severity}'")
        elif severity_value and not normalized_severity:
            block = _replace_or_insert_markdown_field(block, "Severity", "Medium", after_fields=["Exploitability Seen"])
            notes.append(f"{candidate_id}: normalized invalid Severity '{severity_value}' -> 'Medium'")
        if normalized_status:
            block = _replace_or_insert_markdown_field(block, "Status", normalized_status, after_fields=["AI Confidence Guess", "Severity"])
        guess = _security_normalize_confidence_guess_value(ai_guess_value) or "Medium"
        block = _replace_or_insert_markdown_field(block, "AI Confidence Guess", guess, after_fields=["Severity"])

        evidence_value = _optional_field_in_block(block, "Evidence")
        evidence_lower = evidence_value.lower()
        if not _optional_field_in_block(block, "Evidence Type"):
            if evidence_lower.startswith("inferred:"):
                inferred_type = "Inferred"
            elif any(token in evidence_value for token in ["`", "()", ":"]) and _security_evidence_has_location(evidence_value):
                inferred_type = "Direct Code"
            elif _security_evidence_has_location(evidence_value):
                inferred_type = "Pattern Match"
            else:
                inferred_type = "Inferred"
            block = _replace_or_insert_markdown_field(block, "Evidence Type", inferred_type, after_fields=["Evidence"])
            notes.append(f"{candidate_id}: inserted missing Evidence Type '{inferred_type}'")
        if not _optional_field_in_block(block, "Data Flow Seen"):
            data_flow = "Partial" if any(token in evidence_lower for token in ["user", "input", "request", "parameter", "args", "body"]) else "No"
            block = _replace_or_insert_markdown_field(block, "Data Flow Seen", data_flow, after_fields=["Evidence Type"])
            notes.append(f"{candidate_id}: inserted missing Data Flow Seen '{data_flow}'")
        if not _optional_field_in_block(block, "Exploitability Seen"):
            exploitability = "Partial" if (normalized_status or "") in {"Confirmed", "Likely", "Needs Review"} else "No"
            block = _replace_or_insert_markdown_field(block, "Exploitability Seen", exploitability, after_fields=["Data Flow Seen"])
            notes.append(f"{candidate_id}: inserted missing Exploitability Seen '{exploitability}'")

        # Remove legacy/conflicting confidence fields. The only AI confidence
        # field in candidate artifacts is AI Confidence Guess.
        block = re.sub(r"(?im)^\s*[-*]?\s*Confidence\s*:\s*.*\n?", "", block, count=1)
        block = re.sub(r"(?im)^\s*[-*]?\s*Confidence Guess\s*:\s*.*\n?", "", block, count=1)
        block = re.sub(r"(?im)^\s*[-*]?\s*Confidence Score\s*:\s*.*\n?", "", block, count=1)
        if ai_guess_value and guess != ai_guess_value:
            notes.append(f"{candidate_id}: normalized AI Confidence Guess '{ai_guess_value}' -> '{guess}'")
        notes.extend(f"{candidate_id}: {note}" for note in block_notes if "Confidence Score" not in note)
        pieces.append(block)
        cursor = end
    pieces.append(result[cursor:])
    result = "".join(pieces)

    candidates = _parse_security_candidates("normalized-security-candidates.md", result)
    if candidates:
        index_rows = [["ID", "Severity", "AI Confidence Guess", "Status", "Area", "Evidence Summary"], ["---", "---", "---", "---", "---", "---"]]
        for candidate in candidates:
            candidate_id = candidate.get("Candidate ID", "CAND-???")
            severity = _security_normalize_severity_value(candidate.get("Severity", "")) or "Medium"
            guess = _security_normalize_confidence_guess_value(candidate.get("AI Confidence Guess", "")) or "Medium"
            status = _security_normalize_status_value(candidate.get("Status", "")) or "Needs Review"
            area = candidate.get("Area", "").strip()
            if _security_is_placeholder_text(area):
                area = "Needs evidence review"
            evidence_summary = (candidate.get("Evidence") or candidate.get("File") or candidate.get("Reason") or "").strip()
            if _security_is_placeholder_text(evidence_summary):
                evidence_summary = "Limitation: candidate block still needs concrete evidence"
            evidence_summary = evidence_summary.replace("|", "/")
            if len(evidence_summary) > 180:
                evidence_summary = evidence_summary[:177] + "..."
            index_rows.append([candidate_id, severity, guess, status, area.replace("|", "/"), evidence_summary])
        result = _replace_markdown_section_body(result, "Candidate Index", "\n".join("| " + " | ".join(row) + " |" for row in index_rows))
        notes.append("rebuilt Candidate Index from normalized candidate blocks")
    return result, notes

def _security_confidence_consistency_score(confidence: str, evidence_score: int, *, status: str = "", severity: str = "") -> int:
    confidence_score = _security_parse_confidence_score(confidence)
    if confidence_score is None:
        return 0
    severity = (severity or "").strip().title()
    status = (status or "").strip()
    if status == "No Finding":
        if confidence_score >= 80 and evidence_score >= 22:
            return 18
        if 50 <= confidence_score <= 79 and evidence_score >= 16:
            return 16
        if confidence_score < 50:
            return 12
        return 8

    if confidence_score >= 80:
        if evidence_score >= 24:
            return 20
        if evidence_score >= 18:
            return 15
        return 7
    if confidence_score >= 50:
        if evidence_score >= 18:
            return 17
        if evidence_score >= 12:
            return 14
        return 9
    if evidence_score < 18:
        return 16
    if severity in {"Critical", "High"} and evidence_score >= 24:
        return 11
    return 13


def _security_average(values: list[int], default: int = 0) -> int:
    if not values:
        return default
    return round(sum(values) / len(values))


def _security_score_status(total: int, category_scores: dict[str, int], thresholds: dict[str, int]) -> tuple[str, list[str]]:
    failures: list[str] = []
    if total < thresholds.get("total", 0):
        failures.append(f"Total score below threshold: {total}/{thresholds.get('total', 0)}.")
    for key, threshold in thresholds.items():
        if key == "total":
            continue
        value = category_scores.get(key, 0)
        if value < threshold:
            label = key.replace("_", " ").title()
            failures.append(f"{label} score below threshold: {value}/{threshold}.")
    return ("FAIL" if failures else "PASS"), failures


def _render_security_score_report(
    *,
    title: str,
    artifact: str,
    status: str,
    scores: dict[str, int],
    max_scores: dict[str, int],
    thresholds: dict[str, int],
    failures: list[str],
    details: list[str],
    retry_guidance: list[str],
) -> str:
    total = scores.get("total", 0)
    max_total = max_scores.get("total", 100)
    lines = [
        f"# {title}",
        "",
        f"Status: {status}",
        f"Artifact: {artifact}",
        f"Total score: {total}/{max_total}",
        "",
        "## Score Summary",
        "| Category | Score | Max | Threshold |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key, label in [
        ("format", "Format"),
        ("evidence", "Evidence"),
        ("confidence", "Confidence"),
        ("coverage", "Coverage"),
        ("consistency", "Consistency"),
        ("source_mapping", "Source Mapping"),
        ("total", "Total"),
    ]:
        if key not in scores:
            continue
        threshold = thresholds.get(key, "-")
        lines.append(f"| {label} | {scores[key]} | {max_scores.get(key, '-')} | {threshold} |")
    lines.extend(["", "## Failure Reasons"])
    lines.extend([f"- {item}" for item in failures] or ["- None."])
    lines.extend(["", "## Details"])
    lines.extend(details or ["- No detailed scoring notes."])
    lines.extend(["", "## Retry Guidance"])
    lines.extend(retry_guidance or ["- No retry needed."])
    return "\n".join(lines).rstrip() + "\n"


def _parse_security_quality_scores(output_dir: Path) -> dict[str, dict[str, int | str]]:
    import re

    scores: dict[str, dict[str, int | str]] = {}
    for path in sorted(output_dir.glob("security-candidates-agent-*-score.md")):
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        artifact_match = re.search(r"(?m)^Artifact:\s*(.+?)\s*$", text)
        total_match = re.search(r"(?m)^Total score:\s*(\d+)\s*/\s*100\s*$", text)
        status_match = re.search(r"(?m)^Status:\s*(PASS|FAIL)\s*$", text)
        if not artifact_match or not total_match:
            continue
        artifact = artifact_match.group(1).strip()
        scores[artifact] = {
            "artifact": artifact,
            "score_file": path.name,
            "total": int(total_match.group(1)),
            "status": status_match.group(1) if status_match else "UNKNOWN",
        }
    return scores

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


def _security_evidence_type_base_score(value: str) -> int:
    normalized = (value or "").strip().lower().replace("_", " ").replace("-", " ")
    mapping = {
        "direct code": 45,
        "direct config": 40,
        "dependency": 35,
        "pattern match": 25,
        "inferred": 10,
    }
    if normalized in mapping:
        return mapping[normalized]
    if "code" in normalized:
        return 45
    if "config" in normalized or "configuration" in normalized:
        return 40
    if "dependency" in normalized or "manifest" in normalized or "package" in normalized:
        return 35
    if "pattern" in normalized:
        return 25
    if "infer" in normalized or "assumption" in normalized:
        return 10
    return 0


def _security_data_flow_score(value: str) -> int:
    lowered = (value or "").strip().lower()
    if lowered in {"yes", "true", "complete", "full"}:
        return 15
    if lowered in {"partial", "partially", "limited"}:
        return 8
    return 0


def _security_exploitability_score(value: str) -> int:
    lowered = (value or "").strip().lower()
    if lowered in {"yes", "true", "external", "reachable"}:
        return 10
    if lowered in {"partial", "partially", "possible", "limited", "internal"}:
        return 5
    if "hardening" in lowered:
        return 2
    return 0


def _security_quality_bonus(items: list[dict[str, str]], quality_scores: dict[str, dict[str, int | str]]) -> int:
    totals: list[int] = []
    for item in items:
        score = quality_scores.get(item.get("Source Artifact", ""), {}).get("total")
        if isinstance(score, int):
            totals.append(score)
    average = _security_average(totals, 0)
    if average >= 85:
        return 5
    if average >= 75:
        return 3
    return 0


def _security_python_confidence_score(items: list[dict[str, str]], evidence: str, quality_scores: dict[str, dict[str, int | str]]) -> tuple[int, list[str]]:
    primary = items[0] if items else {}
    evidence_type_score = max((_security_evidence_type_base_score(item.get("Evidence Type", "")) for item in items), default=0)
    if evidence_type_score <= 0:
        evidence_type_score = min(45, round(_security_evidence_score_value(evidence, status=primary.get("Status", "")) / 30 * 45))

    consensus_count = len(items)
    if consensus_count >= 3:
        consensus_score = 25
    elif consensus_count >= 2:
        consensus_score = 15
    else:
        consensus_score = 5

    data_flow_score = max((_security_data_flow_score(item.get("Data Flow Seen", "")) for item in items), default=0)
    exploitability_score = max((_security_exploitability_score(item.get("Exploitability Seen", "")) for item in items), default=0)
    quality_bonus = _security_quality_bonus(items, quality_scores)

    penalty = 0
    if not _security_evidence_has_location(evidence):
        penalty += 20
    if any((item.get("AI Confidence Guess", "").lower() == "high" and _security_evidence_score_value(item.get("Evidence", ""), status=item.get("Status", "")) < 18) for item in items):
        penalty += 5
    if primary.get("Severity", "").title() in {"Critical", "High"} and evidence_type_score <= 10:
        penalty += 10

    score = max(0, min(100, evidence_type_score + consensus_score + data_flow_score + exploitability_score + quality_bonus - penalty))
    basis = [
        f"Evidence type score: {evidence_type_score}/45.",
        f"Multi-agent consensus score: {consensus_score}/25 from {consensus_count} agent(s).",
        f"Data flow score: {data_flow_score}/15.",
        f"Exploitability score: {exploitability_score}/10.",
        f"Agent quality bonus: {quality_bonus}/5.",
    ]
    if penalty:
        basis.append(f"Penalty applied: -{penalty} for weak or inconsistent support.")
    return score, basis


def _security_consensus_confidence(confidences: list[str], evidence: str, consensus_count: int) -> str:
    numeric_scores = [score for score in (_security_parse_confidence_score(value) for value in confidences) if score is not None]
    base_score = _security_average(numeric_scores, 30)
    has_location = _security_evidence_has_location(evidence)
    if consensus_count >= 3 and has_location:
        base_score += 20
    elif consensus_count >= 2 and has_location:
        base_score += 12
    elif has_location:
        base_score += 5
    else:
        base_score = min(base_score, 45)
    return str(max(0, min(100, round(base_score))))


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
            "Area", "File", "Location", "Function/Class", "Evidence", "Evidence Type",
            "Data Flow Seen", "Exploitability Seen", "Severity", "Severity Guess",
            "AI Confidence Guess", "Confidence Score", "Confidence", "Confidence Guess",
            "Status", "Reason", "Impact", "Recommendation",
        ]:
            value = _optional_field_in_block(block, field)
            if value:
                item[field] = value
        if "Severity" not in item and "Severity Guess" in item:
            item["Severity"] = item["Severity Guess"]
        if "AI Confidence Guess" not in item and "Confidence Guess" in item:
            item["AI Confidence Guess"] = item["Confidence Guess"]
        if "AI Confidence Guess" not in item and "Confidence" in item:
            item["AI Confidence Guess"] = item["Confidence"]
        if "AI Confidence Guess" not in item and "Confidence Score" in item:
            item["AI Confidence Guess"] = _security_confidence_guess_from_score(_security_parse_confidence_score(item["Confidence Score"]))
        if "AI Confidence Guess" in item:
            item["AI Confidence Guess"] = _security_normalize_confidence_guess_value(item["AI Confidence Guess"]) or "Medium"
        if "Location" not in item and "File" in item:
            item["Location"] = item["File"]
        candidates.append(item)
    return candidates


def _security_heuristic_candidate(
    index: int,
    *,
    title: str,
    area: str,
    file: str,
    function_class: str,
    evidence: str,
    evidence_type: str,
    severity: str,
    confidence: str,
    status: str,
    data_flow: str,
    exploitability: str,
    reason: str,
    impact: str,
    recommendation: str,
) -> dict[str, str]:
    return {
        "Candidate ID": f"HEUR-{index:03d}",
        "Title": title,
        "Source Artifact": "security-context.md",
        "Area": area,
        "File": file,
        "Function/Class": function_class,
        "Evidence": evidence,
        "Evidence Type": evidence_type,
        "Data Flow Seen": data_flow,
        "Exploitability Seen": exploitability,
        "Severity": severity,
        "AI Confidence Guess": confidence,
        "Status": status,
        "Reason": reason,
        "Impact": impact,
        "Recommendation": recommendation,
        "Raw Block": "",
    }


def _security_heuristic_candidates_from_context(text: str) -> list[dict[str, str]]:
    import re

    candidates: list[dict[str, str]] = []

    def add(**kwargs: str) -> None:
        candidates.append(_security_heuristic_candidate(len(candidates) + 1, **kwargs))

    blocks: list[tuple[str, str]] = []
    current_file = "security-context.md"
    current_lines: list[str] = []
    for line in text.splitlines():
        header = re.match(r"^###\s+(.+?)\s*$", line)
        if header:
            if current_lines:
                blocks.append((current_file, "\n".join(current_lines)))
            current_file = header.group(1).strip()
            current_lines = []
            continue
        if current_file != "security-context.md":
            current_lines.append(line)
    if current_lines:
        blocks.append((current_file, "\n".join(current_lines)))
    if not blocks:
        blocks = [("security-context.md", text)]

    def evidence_lines(body: str, pattern: str, limit: int = 3) -> str:
        matches = []
        for raw_line in body.splitlines():
            if re.search(pattern, raw_line, re.IGNORECASE):
                matches.append(raw_line.strip())
            if len(matches) >= limit:
                break
        return " | ".join(matches) or body.strip()[:240]

    seen: set[tuple[str, str]] = set()
    secret_pattern = r"Bearer|api[_-]?key|api[_-]?token|secret|private[_-]?key|jwt"
    credential_pattern = r"pass(word)?|pwd|account"
    deserialization_pattern = r"BinaryFormatter|ObjectInputStream|pickle\.loads|yaml\.load|deserialize"
    path_write_pattern = r"AppendAllText|WriteAllText|writeFile|open\(|FileOutputStream|getName|username|user[_-]?input|request|param|args|argv"
    for file_path, body in blocks:
        lowered = body.lower()

        if re.search(r"\b(bearer|api[_-]?key|api[_-]?token|secret|private[_-]?key|jwt)\b", lowered):
            key = (file_path, "credential-token")
            if key not in seen:
                seen.add(key)
                add(
                    title="Possible hard-coded token or secret in source/config",
                    area="Secrets and credentials exposure",
                    file=file_path,
                    function_class="Unknown",
                    evidence=f"{file_path}: {evidence_lines(body, secret_pattern)}",
                    evidence_type="Direct Code",
                    severity="High",
                    confidence="Medium",
                    status="Needs Review",
                    data_flow="Partial",
                    exploitability="Partial",
                    reason="Security context contains token/secret-looking material in a source or configuration excerpt.",
                    impact="A real exposed token or secret may allow unauthorized access to dependent systems.",
                    recommendation="Remove hard-coded secrets, rotate exposed credentials, and load secrets from protected runtime configuration.",
                )

        if re.search(r"\b(pass(word)?|pwd|account)\b", lowered):
            key = (file_path, "password-field")
            if key not in seen:
                seen.add(key)
                add(
                    title="Possible plaintext credential field or value",
                    area="Secrets and credentials exposure",
                    file=file_path,
                    function_class="Unknown",
                    evidence=f"{file_path}: {evidence_lines(body, credential_pattern)}",
                    evidence_type="Direct Code",
                    severity="Medium",
                    confidence="Medium",
                    status="Needs Review",
                    data_flow="Partial",
                    exploitability="Partial",
                    reason="Security context contains account/password-looking fields or values without visible protected storage.",
                    impact="Local files, logs, backups, or repositories may expose user credentials.",
                    recommendation="Avoid storing passwords when possible. If persistence is required, use OS-protected credential storage or encrypted secret storage.",
                )

        if re.search(r"\b(binaryformatter|objectinputstream|pickle\.loads|yaml\.load|deserialize)\b", lowered):
            key = (file_path, "unsafe-deserialization")
            if key not in seen:
                seen.add(key)
                add(
                    title="Potential unsafe deserialization usage",
                    area="Deserialization and dynamic execution",
                    file=file_path,
                    function_class="Unknown",
                    evidence=f"{file_path}: {evidence_lines(body, deserialization_pattern)}",
                    evidence_type="Pattern Match",
                    severity="Medium",
                    confidence="Medium",
                    status="Needs Review",
                    data_flow="Partial",
                    exploitability="Partial",
                    reason="Security context contains deserialization APIs or serialized data markers that may be unsafe with untrusted input.",
                    impact="If attacker-controlled data reaches deserialization, it may enable object injection, code execution, or application compromise.",
                    recommendation="Use safe parsers and explicit DTOs. Reject untrusted serialized payloads and document trusted file boundaries.",
                )

        path_write = re.search(r"\b(appendalltext|writealltext|writefile|open\(|fileoutputstream)\b", lowered)
        dynamic_name = re.search(r"\b(getname|username|user[_-]?input|request|param|args|argv)\b", lowered)
        if path_write and dynamic_name:
            key = (file_path, "dynamic-path-write")
            if key not in seen:
                seen.add(key)
                add(
                    title="Dynamic value appears to influence a file write path",
                    area="Unsafe file/path handling",
                    file=file_path,
                    function_class="Unknown",
                    evidence=f"{file_path}: {evidence_lines(body, path_write_pattern)}",
                    evidence_type="Direct Code",
                    severity="Medium",
                    confidence="Medium",
                    status="Needs Review",
                    data_flow="Partial",
                    exploitability="Partial",
                    reason="A runtime/user-like value appears near file write path construction without visible normalization in the excerpt.",
                    impact="If unsanitized, path traversal or unintended file overwrite may be possible.",
                    recommendation="Sanitize path components with a strict allowlist and resolve/verify final paths stay under the intended directory.",
                )

    return candidates


def validate_security_candidates(ctx: WorkflowFunctionContext, artifact: str = "security-candidates-agent-1.md") -> None:
    """Validate and score one AI security candidate artifact.

    Candidate files may contain qualitative AI confidence guesses only. Python
    computes official numeric Confidence Score later in combine_security_candidates.
    Small Markdown formatting mistakes are normalized before strict checks.
    """
    artifact = (artifact or "").strip() or "security-candidates-agent-1.md"
    path = ctx.output_dir / artifact
    text = ctx.read_text(path)
    if not text.strip():
        raise WorkflowFunctionError(f"{artifact} is empty.")

    normalized_text, normalization_notes = _normalize_security_candidate_artifact_text(text)
    if normalized_text != text:
        text = normalized_text
        ctx.write_text(path, text)

    if "Status: DONE" not in text:
        raise WorkflowFunctionError(f"{artifact} must contain 'Status: DONE'.")

    require_sections(text, ["Scan Summary", "Checklist Coverage", "Candidate Index", "Candidates"], artifact)

    summary = _markdown_section_body(text, "Scan Summary")
    overall_guess = (
        _optional_field_in_block(summary, "Overall evidence confidence guess")
        or _optional_field_in_block(summary, "Overall candidate confidence guess")
        or _optional_field_in_block(summary, "Overall candidate confidence score")
    )
    if not overall_guess:
        raise WorkflowFunctionError(
            f"{artifact} Scan Summary must include 'Overall evidence confidence guess: High | Medium | Low'."
        )
    normalized_overall_guess = _security_normalize_confidence_guess_value(overall_guess)
    if not normalized_overall_guess:
        normalized_overall_guess = "Medium"
        normalization_notes.append(
            f"normalized invalid Overall evidence confidence guess '{overall_guess}' -> 'Medium'"
        )

    checklist = _markdown_section_body(text, "Checklist Coverage")
    checklist_rows = _require_markdown_table(
        "Checklist Coverage",
        checklist,
        ["Check", "Status", "Evidence", "Notes"],
        artifact,
    )
    if len(checklist_rows) < 8:
        raise WorkflowFunctionError(f"{artifact} Checklist Coverage must contain at least 8 reviewed security categories.")
    allowed_check_statuses = {"Reviewed", "Finding", "Risk", "Not applicable", "Not Applicable", "Limited"}
    for index, row in enumerate(checklist_rows, start=1):
        check, status, evidence, notes = row
        if not check.strip():
            raise WorkflowFunctionError(f"{artifact} Checklist Coverage row {index} has empty Check.")
        normalized_status = _security_normalize_check_status_value(status)
        if normalized_status not in allowed_check_statuses:
            raise WorkflowFunctionError(
                f"{artifact} Checklist Coverage row {index} has invalid Status '{status}'. "
                "Use Reviewed, Finding, Risk, Not applicable, or Limited."
            )
        if _security_is_placeholder_text(evidence) and not _security_is_limitation_text(notes):
            raise WorkflowFunctionError(
                f"{artifact} Checklist Coverage row {index} must include concrete evidence, a file/config reference, or a stated limitation."
            )
        if _security_is_placeholder_text(notes) and not _security_is_limitation_text(evidence):
            raise WorkflowFunctionError(
                f"{artifact} Checklist Coverage row {index} must include Notes or a stated limitation."
            )

    candidate_index = _markdown_section_body(text, "Candidate Index")
    candidate_index_rows = _require_markdown_table(
        "Candidate Index",
        candidate_index,
        ["ID", "Severity", "AI Confidence Guess", "Status", "Area", "Evidence Summary"],
        artifact,
    )
    if not candidate_index_rows:
        raise WorkflowFunctionError(f"{artifact} Candidate Index must contain at least one CAND row.")

    valid_severities = {"Critical", "High", "Medium", "Low", "Info"}
    valid_statuses = SECURITY_VALID_STATUSES
    index_guess_by_id: dict[str, str] = {}
    for index, row in enumerate(candidate_index_rows, start=1):
        candidate_id, severity, ai_guess, status, area, evidence_summary = row
        if not candidate_id.startswith("CAND-"):
            raise WorkflowFunctionError(f"{artifact} Candidate Index row {index} must start with a CAND-### ID.")
        normalized_severity = _security_normalize_severity_value(severity)
        if normalized_severity not in valid_severities:
            raise WorkflowFunctionError(f"{artifact} Candidate Index row {index} has invalid Severity '{severity}'.")
        severity = normalized_severity
        normalized_guess = _security_normalize_confidence_guess_value(ai_guess)
        if not normalized_guess:
            raise WorkflowFunctionError(
                f"{artifact} Candidate Index row {index} has invalid AI Confidence Guess '{ai_guess}'. Use High, Medium, or Low."
            )
        normalized_status = _security_normalize_status_value(status)
        if normalized_status not in valid_statuses:
            raise WorkflowFunctionError(f"{artifact} Candidate Index row {index} has invalid Status '{status}'.")
        status = normalized_status
        if not area.strip() or not evidence_summary.strip() or evidence_summary.strip() in {"-", "N/A", "Unknown", "TBD"}:
            raise WorkflowFunctionError(f"{artifact} Candidate Index row {index} must include Area and Evidence Summary.")
        index_guess_by_id[candidate_id] = normalized_guess

    candidates = _parse_security_candidates(artifact, text)
    if not candidates:
        raise WorkflowFunctionError(f"{artifact} must include at least one '### CAND-001 - ...' block.")

    candidate_ids = [candidate.get("Candidate ID", "") for candidate in candidates]
    if candidate_ids[0] != "CAND-001":
        raise WorkflowFunctionError(f"{artifact} candidate IDs must start with CAND-001.")
    duplicate_ids = sorted({candidate_id for candidate_id in candidate_ids if candidate_ids.count(candidate_id) > 1})
    if duplicate_ids:
        raise WorkflowFunctionError(f"{artifact} has duplicate candidate IDs: {', '.join(duplicate_ids)}")
    for expected_index, candidate_id in enumerate(candidate_ids, start=1):
        expected_id = f"CAND-{expected_index:03d}"
        if candidate_id != expected_id:
            raise WorkflowFunctionError(
                f"{artifact} candidate IDs must be sequential. Expected {expected_id}, got {candidate_id}."
            )

    index_ids = [row[0] for row in candidate_index_rows]
    if index_ids != candidate_ids:
        raise WorkflowFunctionError(
            f"{artifact} Candidate Index IDs must exactly match Candidates block IDs in order. "
            f"Index: {', '.join(index_ids)}; Blocks: {', '.join(candidate_ids)}."
        )

    for candidate in candidates:
        candidate_id = candidate.get("Candidate ID", "CAND-???")
        raw_block = candidate.get("Raw Block", "")
        for field in [
            "Area", "File", "Function/Class", "Evidence", "Evidence Type", "Data Flow Seen",
            "Exploitability Seen", "Severity", "AI Confidence Guess", "Status", "Reason", "Impact", "Recommendation",
        ]:
            _require_field_in_block(artifact, candidate_id, raw_block, field)

        severity = (candidate.get("Severity") or "").strip()
        normalized_severity = _security_normalize_severity_value(severity)
        if normalized_severity not in valid_severities:
            raise WorkflowFunctionError(
                f"{artifact} {candidate_id} has invalid Severity '{severity}'. Use Critical, High, Medium, Low, or Info."
            )
        severity = normalized_severity

        ai_guess = _security_normalize_confidence_guess_value(candidate.get("AI Confidence Guess", ""))
        if not ai_guess:
            raise WorkflowFunctionError(f"{artifact} {candidate_id} must include AI Confidence Guess: High | Medium | Low.")
        if index_guess_by_id.get(candidate_id) != ai_guess:
            raise WorkflowFunctionError(
                f"{artifact} {candidate_id} AI Confidence Guess must match Candidate Index. "
                f"Index={index_guess_by_id.get(candidate_id)}, Block={ai_guess}."
            )

        status = (candidate.get("Status") or "").strip()
        normalized_status = _security_normalize_status_value(status)
        if normalized_status not in valid_statuses:
            raise WorkflowFunctionError(
                f"{artifact} {candidate_id} has invalid Status '{status}'. "
                "Use Confirmed, Likely, Needs Review, Hardening, False Positive, Not Applicable, or No Finding."
            )
        status = normalized_status

        evidence_type = (candidate.get("Evidence Type") or "").strip()
        if not _security_evidence_type_base_score(evidence_type):
            raise WorkflowFunctionError(
                f"{artifact} {candidate_id} has invalid Evidence Type '{evidence_type}'. "
                "Use Direct Code, Direct Config, Dependency, Pattern Match, or Inferred."
            )

        data_flow = (candidate.get("Data Flow Seen") or "").strip()
        if not _security_data_flow_score(data_flow) and data_flow.lower() not in {"no", "none", "not applicable", "n/a"}:
            raise WorkflowFunctionError(f"{artifact} {candidate_id} Data Flow Seen must be Yes, Partial, No, or Not applicable.")

        exploitability = (candidate.get("Exploitability Seen") or "").strip()
        if not _security_exploitability_score(exploitability) and exploitability.lower() not in {"no", "none", "not applicable", "n/a"}:
            raise WorkflowFunctionError(f"{artifact} {candidate_id} Exploitability Seen must be Yes, Partial, No, or Not applicable.")

        evidence = (candidate.get("Evidence") or "").strip()
        if evidence in {"", "-", "N/A", "Unknown", "TBD"}:
            raise WorkflowFunctionError(f"{artifact} {candidate_id} Evidence must not be empty or placeholder text.")
        if status != "No Finding" and not _security_evidence_has_location(evidence):
            raise WorkflowFunctionError(
                f"{artifact} {candidate_id} Evidence must include file/path/function/config evidence, "
                "or explicitly start with 'Inferred:'."
            )
        if status == "No Finding" and severity != "Info":
            raise WorkflowFunctionError(f"{artifact} {candidate_id} with Status: No Finding must use Severity: Info.")
        if status == "No Finding" and len(candidates) > 1:
            raise WorkflowFunctionError(
                f"{artifact} should not mix Status: No Finding with additional candidate findings."
            )

    candidate_details: list[str] = []
    if normalization_notes:
        candidate_details.extend(f"- Format repair: {note}" for note in normalization_notes)
    candidate_evidence_scores: list[int] = []
    candidate_confidence_scores: list[int] = []
    for candidate in candidates:
        candidate_id = candidate.get("Candidate ID", "CAND-???")
        status = (candidate.get("Status") or "").strip()
        severity = (candidate.get("Severity") or "").strip()
        ai_guess = _security_normalize_confidence_guess_value(candidate.get("AI Confidence Guess", "")) or "Medium"
        evidence = (candidate.get("Evidence") or "").strip()
        evidence_score = _security_evidence_score_value(evidence, status=status)
        evidence_type_score = _security_evidence_type_base_score(candidate.get("Evidence Type", ""))
        combined_evidence_score = min(30, max(evidence_score, round(evidence_type_score / 45 * 30)))
        confidence_score = _security_confidence_guess_score(ai_guess, combined_evidence_score, status=status)
        candidate_evidence_scores.append(combined_evidence_score)
        candidate_confidence_scores.append(confidence_score)
        candidate_details.append(
            f"- {candidate_id}: Severity={severity}, AIConfidenceGuess={ai_guess}, Status={status}, "
            f"EvidenceType={candidate.get('Evidence Type', '')}, EvidenceScore={combined_evidence_score}/30, "
            f"AIConfidenceConsistency={confidence_score}/20"
        )

    checklist_quality_scores: list[int] = []
    for row in checklist_rows:
        _check, status, evidence, _notes = row
        evidence_score = _security_evidence_score_value(evidence, status=status)
        checklist_quality_scores.append(evidence_score)

    format_score = 20
    evidence_score = min(30, _security_average(candidate_evidence_scores, 0))
    confidence_score = min(20, _security_average(candidate_confidence_scores, 0))
    coverage_count_score = min(12, round(len(checklist_rows) / 12 * 12))
    coverage_evidence_score = min(8, round((_security_average(checklist_quality_scores, 0) / 30) * 8))
    coverage_score = min(20, coverage_count_score + coverage_evidence_score)

    consistency_score = 10
    for candidate in candidates:
        severity = (candidate.get("Severity") or "").strip()
        evidence = (candidate.get("Evidence") or "").strip()
        status = (candidate.get("Status") or "").strip()
        ai_guess = _security_normalize_confidence_guess_value(candidate.get("AI Confidence Guess", "")) or "Medium"
        evidence_score_for_candidate = _security_evidence_score_value(evidence, status=status)
        if ai_guess == "High" and evidence_score_for_candidate < 18:
            consistency_score -= 3
        if severity in {"Critical", "High"} and status in {"Hardening", "No Finding", "Not Applicable"}:
            consistency_score -= 2
        if severity == "Info" and status in {"Confirmed", "Likely"}:
            consistency_score -= 2
    consistency_score = max(0, min(10, consistency_score))

    scores = {
        "format": format_score,
        "evidence": evidence_score,
        "confidence": confidence_score,
        "coverage": coverage_score,
        "consistency": consistency_score,
    }
    total = sum(scores.values())
    scores["total"] = total
    max_scores = {"format": 20, "evidence": 30, "confidence": 20, "coverage": 20, "consistency": 10, "total": 100}
    status, failures = _security_score_status(total, scores, SECURITY_SCORE_THRESHOLDS)
    retry_guidance = []
    if failures:
        retry_guidance.extend([
            "The next agent attempt must keep the exact Markdown schema and improve weak scoring categories.",
            "Do not output a final numeric Confidence Score in candidate artifacts; provide AI Confidence Guess plus evidence inputs only.",
            "Provide Evidence Type, Data Flow Seen, Exploitability Seen, and concrete file/function/config evidence for every non-No-Finding candidate.",
            "Cover at least 12 checklist categories with concrete evidence or explicit limitation notes.",
        ])
    score_report = _render_security_score_report(
        title="Security Candidate Validation Score",
        artifact=artifact,
        status=status,
        scores=scores,
        max_scores=max_scores,
        thresholds=SECURITY_SCORE_THRESHOLDS,
        failures=failures,
        details=candidate_details,
        retry_guidance=retry_guidance,
    )
    ctx.write_text(ctx.output_dir / _security_score_artifact_name(artifact), score_report)
    if failures:
        raise WorkflowFunctionError(
            f"{artifact} quality score failed: total {total}/100; "
            f"evidence {evidence_score}/30; confidence {confidence_score}/20; coverage {coverage_score}/20. "
            f"Open output/{_security_score_artifact_name(artifact)} for details."
        )

def combine_security_candidates(ctx: WorkflowFunctionContext) -> None:
    """Merge multiple AI-generated security candidate artifacts into stable normalized findings."""
    candidate_files = sorted(
        path.name
        for path in ctx.output_dir.glob("security-candidates-agent-*.md")
        if not path.name.endswith("-score.md")
    )
    if not candidate_files:
        raise WorkflowFunctionError("No security-candidates-agent-*.md artifacts found to combine.")
    valid_severities = {"Critical", "High", "Medium", "Low", "Info"}
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

    heuristic_candidates = _security_heuristic_candidates_from_context(ctx.read_text(ctx.output_dir / "security-context.md"))
    all_candidates.extend(heuristic_candidates)

    if not all_candidates:
        raise WorkflowFunctionError("No CAND-### entries were found in multi-agent security candidate artifacts.")

    quality_scores = _parse_security_quality_scores(ctx.output_dir)

    grouped: dict[str, list[dict[str, str]]] = {}
    rejected: list[dict[str, str]] = []
    for candidate in all_candidates:
        status = (candidate.get("Status") or "Candidate").strip().title()
        if status in rejected_statuses:
            rejected.append(candidate)
            continue
        evidence = candidate.get("Evidence") or ""
        severity = (candidate.get("Severity") or "Info").strip().title()
        if severity not in valid_severities:
            rejected.append(candidate)
            continue
        ai_guess = _security_normalize_confidence_guess_value(candidate.get("AI Confidence Guess", ""))
        if not ai_guess:
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
        f"- Deterministic heuristic candidates: {len(heuristic_candidates)}",
        f"- Raw candidates: {len(all_candidates)}",
        f"- Accepted groups: {len(grouped)}",
        f"- Rejected candidates: {len(rejected)}",
        "- Confidence Score rule: Python computes the final numeric confidence from evidence type, evidence quality, data flow, exploitability, multi-agent consensus, and agent quality scores.",
        "- Agent quality rule: candidate artifacts must pass Python quality scoring before they can be combined.",
        "",
        "## Agent Quality Scores",
        "| Artifact | Score File | Total Score | Status |",
        "| --- | --- | ---: | --- |",
    ]
    for name in candidate_files:
        score = quality_scores.get(name, {})
        lines.append(
            f"| {name} | {score.get('score_file', 'missing')} | {score.get('total', 0)} | {score.get('status', 'UNKNOWN')} |"
        )
    lines.extend([
        "",
        "## Accepted Findings",
    ])

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
            confidence_value, confidence_basis = _security_python_confidence_score(items, evidence, quality_scores)
            confidence = str(confidence_value)
            status = "Likely" if confidence_value >= 50 and severity != "Info" else "Needs Review"
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
                f"- Confidence Score: {confidence}",
                "- Confidence Basis:",
                *[f"  - {basis}" for basis in confidence_basis],
                f"- Consensus Count: {len(items)}",
                f"- Agent Quality Scores: {', '.join(str(quality_scores.get(item.get('Source Artifact', ''), {}).get('total', 'unknown')) for item in items)}",
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
                f"AIConfidenceGuess={item.get('AI Confidence Guess', 'Unknown')} | "
                f"Evidence={item.get('Evidence', '').strip()[:160] or 'missing'}"
            )

    ctx.write_text(ctx.output_dir / "security-findings.md", "\n".join(lines).rstrip() + "\n")


def _synthesize_security_report_from_findings(security_findings_text: str, project_dir: Path) -> str:
    normalized_findings = _security_normalized_finding_blocks(security_findings_text)
    finding_items: list[dict[str, str]] = []
    for sec_id, block in normalized_findings:
        finding_items.append({
            "id": sec_id,
            "title": block.splitlines()[0].replace(f"## {sec_id} -", "").strip() or "Security finding",
            "area": _optional_field_in_block(block, "Area") or "General",
            "severity": _security_normalize_severity_value(_optional_field_in_block(block, "Severity")) or "Medium",
            "confidence": str(_security_parse_confidence_score(_optional_field_in_block(block, "Confidence Score")) or 50),
            "evidence": _optional_field_in_block(block, "Evidence") or f"output/security-findings.md: {sec_id}",
            "impact": _optional_field_in_block(block, "Impact") or "Potential security impact depending on runtime exposure and trust boundary.",
            "recommendation": _optional_field_in_block(block, "Recommendation") or "Review and remediate the referenced code/configuration.",
        })

    checklist_categories = [
        "Secrets and credentials exposure",
        "Authentication and authorization",
        "Input validation and output encoding",
        "Injection risks",
        "Unsafe file/path handling",
        "Deserialization or dynamic execution",
        "SSRF and outbound HTTP",
        "Web security controls",
        "Dependency and configuration risks",
        "Sensitive logging and error disclosure",
    ]
    checklist_rows = []
    for category in checklist_categories:
        matching = next((item for item in finding_items if item["area"].lower() == category.lower()), None)
        if matching:
            checklist_rows.append((category, "Finding", f"{matching['id']}: {matching['evidence']}", "Accepted by Python-combined security findings."))
        elif finding_items:
            checklist_rows.append((category, "Reviewed", "Limitation: no accepted finding in this category after multi-agent candidate filtering", "No accepted finding for this category."))
        else:
            checklist_rows.append((category, "Reviewed", "Limitation: no accepted finding after multi-agent candidate filtering", "No confirmed vulnerability candidate was accepted."))

    overall_severity = "Info"
    if finding_items:
        overall_severity = _security_best_severity([item["severity"] for item in finding_items])
    overall_confidence = str(max((_security_parse_confidence_score(item["confidence"]) or 0 for item in finding_items), default=80))
    if not finding_items:
        overall_confidence = "80"

    lines = [
        "Status: DONE",
        "",
        "# Security Vulnerability Report",
        "",
        "## Summary",
        f"- Overall risk level: {overall_severity}",
        f"- Overall confidence score: {overall_confidence}",
        (
            f"- Python-combined security findings accepted {len(finding_items)} finding(s) for final review."
            if finding_items
            else "- Multi-agent candidate filtering did not accept any confirmed security vulnerability findings for the reviewed scope."
        ),
        "",
        "## Scan Scope",
        f"- Project path: {project_dir}",
        "- Languages/frameworks detected: see security-findings.md and security-context.md for collected project context.",
        (
            "- Files or areas reviewed from accepted Python-combined findings and candidate evidence: "
            + ", ".join(sorted({item["area"] for item in finding_items}))
            if finding_items
            else "- Files or areas reviewed from accepted Python-combined findings and candidate evidence: no accepted findings were produced."
        ),
        "- Multi-agent candidate artifacts reviewed: security-candidates-agent-1.md, security-candidates-agent-2.md, security-candidates-agent-3.md and score artifacts.",
        "",
        "## Method",
        "- Static code and configuration review based on Project Path inspection by multiple independent AI agents.",
        "- Multiple independent same-task AI candidate scans.",
        "- Python scoring, filtering, deduplication, and official numeric confidence calculation into security-findings.md.",
        "- Candidate quality score artifacts were used to understand evidence quality and AI guess reliability.",
        "- Final report generated only from accepted Python-combined findings.",
        "- This is not a replacement for SAST, DAST, dependency scanning, or manual runtime security testing.",
        "",
        "## Security Checklist",
        "| Check | Status | Evidence | Notes |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(f"| {check} | {status} | {evidence} | {notes} |" for check, status, evidence, notes in checklist_rows)
    lines.extend([
        "",
        "## Findings",
    ])
    if finding_items:
        for index, item in enumerate(finding_items, start=1):
            lines.extend([
                f"### VULN-{index:03d} - {item['title']}",
                f"- Source Finding ID: {item['id']}",
                f"- Severity: {item['severity']}",
                f"- Confidence Score: {item['confidence']}",
                f"- Evidence: {item['evidence']}",
                f"- Impact: {item['impact']}",
                f"- Recommendation: {item['recommendation']}",
                "",
            ])
    else:
        lines.extend([
            "No confirmed vulnerabilities found.",
            "",
        ])
    lines.extend([
        "",
        "## Risk Matrix",
        "| ID | Source Finding ID | Severity | Confidence Score | Area | Evidence Summary | Status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    if finding_items:
        for index, item in enumerate(finding_items, start=1):
            evidence_summary = item["evidence"].replace("|", "/")
            if len(evidence_summary) > 160:
                evidence_summary = evidence_summary[:157] + "..."
            lines.append(
                f"| VULN-{index:03d} | {item['id']} | {item['severity']} | {item['confidence']} | "
                f"{item['area'].replace('|', '/')} | {evidence_summary} | Needs remediation |"
            )
    else:
        lines.append("| NONE | NONE | Info | 80 | Reviewed scope | No confirmed vulnerabilities found after multi-agent candidate filtering | Closed |")
    lines.extend([
        "",
        "## Recommendations",
        "- Prioritize accepted High and Medium severity findings from the Risk Matrix.",
        "- Continue targeted manual review for high-risk authentication, authorization, input handling, file handling, and configuration paths.",
        "- Run dedicated SAST, dependency, secret, and runtime security tests if stronger assurance is required.",
        "- Re-run this workflow after material code, dependency, or configuration changes.",
        "",
        "## Limitations",
        (
            "- Findings are static-analysis candidates accepted from workflow evidence and still require owner review before production severity decisions."
            if finding_items
            else "- No accepted SEC findings were produced by security-findings.md, so this report summarizes a no-finding result rather than confirmed vulnerabilities."
        ),
        "- Confidence is limited by available source context, static review depth, model behavior, and lack of runtime exploit validation.",
        "- Candidate artifacts may include low-evidence or rejected candidates that were intentionally not promoted to final findings.",
        "",
    ])
    return "\n".join(lines)


def validate_security_report(ctx: WorkflowFunctionContext, artifact: str = "security-report.md") -> None:
    path = ctx.output_dir / artifact
    text = ctx.read_text(path)
    if not text.strip():
        raise WorkflowFunctionError(f"{artifact} is empty.")
    security_findings_text = ctx.read_text(ctx.output_dir / "security-findings.md")
    normalized_preview = _security_normalized_finding_blocks(security_findings_text)
    report_is_stale_no_finding = bool(normalized_preview) and "No confirmed vulnerabilities found" in text
    report_missing_source_findings = bool(normalized_preview) and any(sec_id not in text for sec_id, _block in normalized_preview)
    if "Status: DONE" not in text or report_is_stale_no_finding or report_missing_source_findings:
        synthesized = _synthesize_security_report_from_findings(security_findings_text, ctx.project_dir)
        if synthesized:
            ctx.write_text(path, synthesized)
            text = synthesized
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
    if not any(f"Overall risk level: {severity}" in summary for severity in valid_severities):
        raise WorkflowFunctionError(
            f"{artifact} Summary must include 'Overall risk level: Critical|High|Medium|Low|Info'."
        )
    overall_confidence = _optional_field_in_block(summary, "Overall confidence score")
    if not overall_confidence:
        raise WorkflowFunctionError(
            f"{artifact} Summary must include 'Overall confidence score: <integer 0-100>'."
        )
    _security_require_confidence_score(overall_confidence, artifact, "Overall confidence score")

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
    allowed_check_statuses = {"Reviewed", "Finding", "Risk", "Not applicable", "Not Applicable", "Limited"}
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

            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence Score")
            _security_require_confidence_score(confidence, artifact, f"{finding_id} Confidence Score")

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
        ["ID", "Source Finding ID", "Severity", "Confidence Score", "Area", "Evidence Summary", "Status"],
        artifact,
    )
    for index, row in enumerate(risk_matrix_rows, start=1):
        if row[0] != "NONE" and not row[0].startswith("VULN-"):
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} ID must be VULN-### or NONE.")
        if row[1] != "NONE" and not row[1].startswith("SEC-"):
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} Source Finding ID must be SEC-### or NONE.")
        if row[2] not in valid_severities:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} has invalid Severity '{row[2]}'.")
        _security_require_confidence_score(row[3], artifact, f"Risk Matrix row {index} Confidence Score")
        if not row[4] or not row[5] or not row[6]:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix row {index} must fill Area, Evidence Summary, and Status.")
    if finding_ids:
        missing = [finding_id for finding_id in finding_ids if finding_id not in risk_matrix]
        if missing:
            raise WorkflowFunctionError(f"{artifact} Risk Matrix missing finding IDs: {', '.join(missing)}")
        for finding_id, block in finding_blocks:
            source_id = _require_field_in_block(artifact, finding_id, block, "Source Finding ID")
            severity = _require_field_in_block(artifact, finding_id, block, "Severity")
            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence Score")
            matching_rows = [line for line in risk_matrix.splitlines() if f"| {finding_id} |" in line]
            if not matching_rows:
                raise WorkflowFunctionError(f"{artifact} Risk Matrix missing row for {finding_id}.")
            row = matching_rows[0]
            if f"| {source_id} |" not in row or f"| {severity} |" not in row or f"| {confidence} |" not in row:
                raise WorkflowFunctionError(
                    f"{artifact} Risk Matrix row for {finding_id} must repeat Source Finding ID, Severity, and Confidence Score."
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
                _security_require_confidence_score(row[3], artifact, "Risk Matrix no-finding row Confidence Score")

    report_details: list[str] = []
    finding_evidence_scores: list[int] = []
    finding_confidence_scores: list[int] = []
    if finding_blocks:
        for finding_id, block in finding_blocks:
            severity = _require_field_in_block(artifact, finding_id, block, "Severity")
            confidence = _require_field_in_block(artifact, finding_id, block, "Confidence Score")
            evidence = _require_field_in_block(artifact, finding_id, block, "Evidence")
            evidence_score = _security_evidence_score_value(evidence, status="Finding")
            confidence_score = _security_confidence_consistency_score(
                confidence, evidence_score, status="Finding", severity=severity
            )
            finding_evidence_scores.append(evidence_score)
            finding_confidence_scores.append(confidence_score)
            report_details.append(
                f"- {finding_id}: Severity={severity}, ConfidenceScore={confidence}, "
                f"EvidenceScore={evidence_score}/30, ConfidenceScore={confidence_score}/20"
            )
    else:
        no_finding_evidence = (
            "output/security-findings.md: No accepted SEC findings after multi-agent candidate filtering; "
            "reviewed output/security-candidates-agent-1.md, output/security-candidates-agent-2.md, "
            "and output/security-candidates-agent-3.md."
        )
        finding_evidence_scores.append(_security_evidence_score_value(no_finding_evidence, status="No Finding"))
        finding_confidence_scores.append(16)
        report_details.append("- NONE: no accepted SEC findings; report uses complete no-finding risk matrix row.")

    checklist_quality_scores = [
        _security_evidence_score_value(row[2], status=row[1]) for row in checklist_rows
    ]
    format_score = 20
    evidence_score = min(30, _security_average(finding_evidence_scores, 0))
    confidence_score = min(20, _security_average(finding_confidence_scores, 0))
    coverage_count_score = min(12, round(len(checklist_rows) / 10 * 12))
    coverage_evidence_score = min(8, round((_security_average(checklist_quality_scores, 0) / 30) * 8))
    coverage_score = min(20, coverage_count_score + coverage_evidence_score)
    source_mapping_score = 10
    if finding_ids:
        if missing_source_ids:
            source_mapping_score = 0
        elif len(mapped_source_ids) != len(set(mapped_source_ids)):
            source_mapping_score = 7
        else:
            source_mapping_score = 10
    consistency_score = 10
    for finding_id, block in finding_blocks:
        severity = _require_field_in_block(artifact, finding_id, block, "Severity")
        confidence = _require_field_in_block(artifact, finding_id, block, "Confidence Score")
        evidence = _require_field_in_block(artifact, finding_id, block, "Evidence")
        evidence_score_for_finding = _security_evidence_score_value(evidence, status="Finding")
        confidence_value = _security_parse_confidence_score(confidence) or 0
        if confidence_value >= 80 and evidence_score_for_finding < 18:
            consistency_score -= 3
        if severity == "Info" and confidence_value >= 80:
            consistency_score -= 1
    consistency_score = max(0, min(10, consistency_score))

    scores = {
        "format": format_score,
        "evidence": evidence_score,
        "confidence": confidence_score,
        "coverage": coverage_score,
        "consistency": consistency_score,
        "source_mapping": source_mapping_score,
    }
    total = min(100, format_score + evidence_score + confidence_score + coverage_score + consistency_score + source_mapping_score)
    scores["total"] = total
    max_scores = {
        "format": 20,
        "evidence": 30,
        "confidence": 20,
        "coverage": 20,
        "consistency": 10,
        "source_mapping": 10,
        "total": 100,
    }
    status, failures = _security_score_status(total, scores, SECURITY_REPORT_SCORE_THRESHOLDS)
    retry_guidance = []
    if failures:
        retry_guidance.extend([
            "The next report attempt must preserve every accepted SEC finding and include numeric Confidence Score for every VULN.",
            "Every VULN must include concrete evidence copied or summarized from security-findings.md.",
            "Risk Matrix rows must repeat ID, Source Finding ID, Severity, and numeric Confidence Score exactly.",
            "Checklist evidence must cite reviewed files, configs, or explicit limitations.",
        ])
    score_report = _render_security_score_report(
        title="Security Report Validation Score",
        artifact=artifact,
        status=status,
        scores=scores,
        max_scores=max_scores,
        thresholds=SECURITY_REPORT_SCORE_THRESHOLDS,
        failures=failures,
        details=report_details,
        retry_guidance=retry_guidance,
    )
    ctx.write_text(ctx.output_dir / _security_report_score_artifact_name(artifact), score_report)
    if failures:
        raise WorkflowFunctionError(
            f"{artifact} quality score failed: total {total}/100; "
            f"evidence {evidence_score}/30; confidence {confidence_score}/20; coverage {coverage_score}/20. "
            f"Open output/{_security_report_score_artifact_name(artifact)} for details."
        )

def generate_security_report(ctx: WorkflowFunctionContext) -> None:
    security_findings_text = ctx.read_text(ctx.output_dir / "security-findings.md")
    if not security_findings_text.strip():
        raise WorkflowFunctionError("security-findings.md is missing or empty.")
    report = _synthesize_security_report_from_findings(security_findings_text, ctx.project_dir)
    if not report.strip():
        raise WorkflowFunctionError("Could not generate security-report.md from security-findings.md.")
    ctx.write_text(ctx.output_dir / "security-report.md", report)


def finalize_security_report(ctx: WorkflowFunctionContext) -> None:
    report = ctx.read_text(ctx.output_dir / "security-report.md")
    score = ctx.read_text(ctx.output_dir / "security-report-score.md")
    if "Status: DONE" not in report:
        raise WorkflowFunctionError("security-report.md must contain Status: DONE before finalization.")
    if "Status: PASS" not in score:
        raise WorkflowFunctionError("security-report-score.md must contain Status: PASS before finalization.")
    summary_lines = [
        "Status: DONE",
        "",
        "# Security Scan Finalized",
        "",
        "- Final report: output/security-report.md",
        "- Validation score: output/security-report-score.md",
    ]
    for line in report.splitlines():
        if line.startswith("- Overall risk level:") or line.startswith("- Overall confidence score:"):
            summary_lines.append(line)
    ctx.write_text(ctx.output_dir / "security-final.md", "\n".join(summary_lines).rstrip() + "\n")

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
    "generate_security_report": generate_security_report,
    "finalize_security_report": finalize_security_report,
    "validate_security_candidates": validate_security_candidates,
    "validate_spec": validate_spec,
    "validate_todo": validate_todo,
    "require_status_pass": require_status_pass,
    "run_pytest": run_pytest,
    "validate_security_report": validate_security_report,
}
