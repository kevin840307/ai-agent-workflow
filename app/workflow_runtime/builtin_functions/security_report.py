from __future__ import annotations

from pathlib import Path

from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.core import require_sections
from app.workflow_runtime.builtin_functions.security_common import *


def _render_security_report_from_findings(security_findings_text: str, project_dir: Path) -> str:
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
        rendered = _render_security_report_from_findings(security_findings_text, ctx.project_dir)
        if rendered:
            ctx.write_text(path, rendered)
            text = rendered
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
    report = _render_security_report_from_findings(security_findings_text, ctx.project_dir)
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


__all__ = [
    "_render_security_report_from_findings",
    "validate_security_report",
    "generate_security_report",
    "finalize_security_report",
]
