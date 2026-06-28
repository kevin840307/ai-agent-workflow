You are scanning the selected project for security vulnerabilities.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Do not modify project files. Do not output FILE/CONTENT/END_FILE blocks.
Do not provide exploit instructions, weaponized payloads, or steps to attack real systems.
Focus on defensive code review, risk identification, evidence quality, and remediation guidance.

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

Scan rules:
- Inspect the provided Security Scan Context from output/security-context.md. Treat it as the primary evidence source.
- Do not stop after saying no confirmed vulnerabilities. First complete the Security Checklist and review each category.
- Report confirmed, likely, inferred, and hardening findings when they are security-relevant.
- It is acceptable to use Severity: Info or Low and Confidence: Low for defensive hardening findings when evidence is limited.
- Only say "No confirmed vulnerabilities found." when the checklist found no confirmed, likely, inferred, or hardening findings.
- Every finding must have a stable ID: VULN-001, VULN-002, ...
- Every finding must include Severity, Confidence, Evidence, Impact, and Recommendation.
- Use severity exactly as one of: Critical, High, Medium, Low, Info.
- Use confidence exactly as one of: High, Medium, Low.
- Evidence must be concrete. Prefer file path + function/class/config name + observed code/config behavior.
- If the issue is inferred, Evidence must explicitly start with "Inferred:" and explain the signal.
- Do not invent vulnerabilities that contradict the evidence. When uncertain, lower Confidence instead of pretending certainty.
- Risk Matrix must always be a complete 6-column Markdown table. Do not put "No confirmed vulnerabilities found" in a single-cell row.

Security categories to check:
- Secrets and credentials exposure
- Authentication and authorization
- Input validation and output encoding
- SQL/NoSQL/command/template injection
- Unsafe file/path handling and upload/download
- Deserialization and dynamic code execution
- SSRF and outbound HTTP calls
- XSS, CSRF, CORS, and web security headers
- Dependency, build, and configuration risks
- Logging of sensitive data and error disclosure
- Cryptography, TLS, and randomness
- Rate limiting, resource exhaustion, and denial of service

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

## Method
- Static code and configuration review based on available project context.
- Security checklist review across common vulnerability categories.
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
- Severity: Critical | High | Medium | Low | Info
- Confidence: High | Medium | Low
- Evidence: <file/path/function/config evidence. Include file path and function/class/config when available. If inferred, start with Inferred: and explain why.>
- Impact: <risk impact>
- Recommendation: <defensive remediation>

If and only if there are no confirmed, likely, inferred, or hardening findings, write exactly:
No confirmed vulnerabilities found.

## Risk Matrix
| ID | Severity | Confidence | Area | Evidence Summary | Status |
| --- | --- | --- | --- | --- | --- |
| VULN-001 | Medium | High | Example area | app/example.py: function_name | Needs remediation |

If and only if there are no findings, use this complete row format:
| NONE | Info | High | Reviewed scope | No confirmed vulnerabilities found after checklist review | Closed |

## Recommendations
- Prioritized defensive fixes.
- Suggested tests or validation checks.

## Limitations
- List missing context, files, runtime behavior, dependency lock files, environment data, or assumptions that limit confidence.
