from __future__ import annotations

from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.core import require_sections
from app.workflow_runtime.builtin_functions.security_common import *


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




__all__ = [
    "_security_heuristic_candidate",
    "_security_heuristic_candidates_from_context",
    "validate_security_candidates",
    "combine_security_candidates",
]
