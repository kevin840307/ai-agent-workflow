You are generating the final security vulnerability report from Python-combined multi-agent findings.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Do not modify project files. Do not output FILE/CONTENT/END_FILE blocks.
Do not provide exploit instructions, weaponized payloads, or steps to attack real systems.

Important report rules:
- Use security-findings.md as the source of truth for final findings.
- Do not create new vulnerabilities that are not present as accepted SEC-### findings.
- Do not drop accepted SEC-### findings. Every accepted SEC finding must become one VULN finding.
- Preserve Severity and Confidence from security-findings.md unless you lower confidence due to clearly stated evidence weakness.
- Every VULN must include Source Finding ID, Severity, Confidence, Evidence, Impact, and Recommendation.
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

Security Scan Context:
{{security_context}}

Multi-Agent Candidate Artifacts:
{{security_candidates}}

Python-Combined Security Findings:
{{security_findings}}

Previous Failure Feedback:
{{failure_feedback}}

Return exactly this Markdown structure:

Status: DONE

# Security Vulnerability Report

## Summary
- Overall risk level: Critical | High | Medium | Low | Info
- Overall confidence: High | Medium | Low
- One-paragraph summary.

## Scan Scope
- Project path.
- Languages/frameworks detected.
- Files or areas reviewed from the available project overview and security context.
- Multi-agent candidate artifacts reviewed.

## Method
- Static code and configuration review based on collected project context.
- Multiple independent same-task AI candidate scans.
- Python filtering, deduplication, and confidence merging into security-findings.md.
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
- Confidence: High | Medium | Low
- Evidence: <copy or summarize concrete evidence from SEC-001>
- Impact: <risk impact>
- Recommendation: <defensive remediation>

If and only if there are no accepted SEC findings in security-findings.md, write exactly:
No confirmed vulnerabilities found.

## Risk Matrix
| ID | Source Finding ID | Severity | Confidence | Area | Evidence Summary | Status |
| --- | --- | --- | --- | --- | --- | --- |
| VULN-001 | SEC-001 | Medium | High | Example area | app/example.py: function_name | Needs remediation |

If and only if there are no accepted SEC findings, use this complete row format:
| NONE | NONE | Info | High | Reviewed scope | No confirmed vulnerabilities found after multi-agent candidate filtering | Closed |

## Recommendations
- Prioritized defensive fixes.
- Suggested tests or validation checks.

## Limitations
- List missing context, files, runtime behavior, dependency lock files, environment data, or assumptions that limit confidence.
