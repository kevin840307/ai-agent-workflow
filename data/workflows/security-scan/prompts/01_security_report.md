You are generating the final security vulnerability report from Python-combined multi-agent findings.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Do not modify project files. Do not output FILE/CONTENT/END_FILE blocks.
Do not provide exploit instructions, weaponized payloads, or steps to attack real systems.

Important report rules:
- Use security-findings.md as the source of truth for final findings.
- Do not create new vulnerabilities that are not present as accepted SEC-### findings.
- Do not drop accepted SEC-### findings. Every accepted SEC finding must become one VULN finding.
- Preserve Severity and Python-computed numeric Confidence Score from security-findings.md unless you lower the numeric confidence score due to clearly stated evidence weakness.
- Every VULN must include Source Finding ID, Severity, Confidence Score, Evidence, Impact, and Recommendation.
- Every security bug/finding must visibly include numeric Confidence Score in the finding body and in the Risk Matrix row.
- Keep Status and Confidence Score separate. Never write values like `Needs Review: High confidence`, `Likely - 80`, or `Status: High`.
- In every VULN block, place Confidence Score directly after Severity so reviewers can see each bug numeric security confidence immediately.
- A Python validator will score this final report. Low Evidence, Confidence Score, Coverage, or Source Mapping scores will fail and retry this report step.
- If security-findings.md has no accepted findings, produce a complete no-finding report with the required table row format.

Project Path: {{project_path}}
Workflow Workspace: {{workspace_path}}

Requirement:
{{requirement}}

Project Overview:
{{project_overview}}

Project Profile:
{{project_profile}}

Existing architecture.md:
{{architecture}}

Multi-Agent Candidate Artifacts:
{{security_candidates}}

Candidate Quality Score Artifacts:
{{security_candidate_scores}}

Python-Combined Security Findings:
{{security_findings}}

Previous Failure Feedback:
{{failure_feedback}}

Return exactly this Markdown structure:

Status: DONE

# Security Vulnerability Report

## Summary
- Overall risk level: Critical | High | Medium | Low | Info
- Overall confidence score: 0-100
- One-paragraph summary.

## Scan Scope
- Project path.
- Languages/frameworks detected.
- Files or areas reviewed from accepted Python-combined findings and candidate evidence.
- Multi-agent candidate artifacts reviewed.

## Method
- Static code and configuration review based on Project Path inspection by multiple independent AI agents.
- Multiple independent same-task AI candidate scans.
- Python scoring, filtering, deduplication, and official numeric confidence calculation into security-findings.md.
- Candidate quality score artifacts are used to understand evidence quality and AI guess reliability; final Confidence Score is computed by Python.
- Final report generated only from accepted Python-combined findings.
- Note that this is not a replacement for SAST/DAST/dependency scanning unless those tools are explicitly run elsewhere.

## Security Checklist
| Check | Status | Evidence | Notes |
| --- | --- | --- | --- |
| Secrets and credentials exposure | Reviewed | <file/path or limitation> | <brief result> |
| Authentication and authorization | Reviewed | <file/path or limitation> | <brief result> |
| Input validation and output encoding | Reviewed | <file/path or limitation> | <brief result> |
| Injection risks | Reviewed | <file/path or limitation> | <brief result> |
| Unsafe file/path handling | Reviewed | <file/path or limitation> | <brief result> |
| Deserialization or dynamic execution | Reviewed | <file/path or limitation> | <brief result> |
| SSRF and outbound HTTP | Reviewed | <file/path or limitation> | <brief result> |
| Web security controls | Reviewed | <file/path or limitation> | <brief result> |
| Dependency and configuration risks | Reviewed | <file/path or limitation> | <brief result> |
| Sensitive logging and error disclosure | Reviewed | <file/path or limitation> | <brief result> |

Allowed Status values are exactly: Reviewed, Finding, Risk, Not applicable, Limited.

## Findings
### VULN-001 - <short title>
- Source Finding ID: SEC-001
- Severity: Critical | High | Medium | Low | Info
- Confidence Score: <integer 0-100>
- Evidence: <copy or summarize concrete evidence from SEC-001>
- Impact: <risk impact>
- Recommendation: <defensive remediation>

Every VULN block must include Confidence Score exactly once with an integer value from 0 to 100.

If and only if there are no accepted SEC findings in security-findings.md, write exactly:
No confirmed vulnerabilities found.

## Risk Matrix
| ID | Source Finding ID | Severity | Confidence Score | Area | Evidence Summary | Status |
| --- | --- | --- | --- | --- | --- | --- |
| VULN-001 | SEC-001 | Medium | 85 | Example area | app/example.py: function_name | Needs remediation |

If and only if there are no accepted SEC findings, use this complete row format:
| NONE | NONE | Info | 80 | Reviewed scope | No confirmed vulnerabilities found after multi-agent candidate filtering | Closed |

## Recommendations
- Prioritized defensive fixes.
- Suggested tests or validation checks.

## Limitations
- List missing context, files, runtime behavior, dependency lock files, environment data, direct file-access limitations, or assumptions that limit confidence.
