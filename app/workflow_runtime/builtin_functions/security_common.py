from __future__ import annotations

from pathlib import Path

from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.core import require_sections


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

    This function no longer trusts an AI-produced final Confidence Score.
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




__all__ = [name for name in globals() if not name.startswith("__")]
