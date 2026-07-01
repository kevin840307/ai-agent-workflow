id: security-scan
name: Security Vulnerability Scan
description: Compact multi-agent AI security scan. Python collects a security manifest,
  runs internal consensus Qwen agents with validation/retry in one visible step, combines
  findings, generates and validates the final report, then finalizes artifacts.
kind: custom
active: false
protected: false
deletable: true
skillRoot: ~/.qwen/skills
promptRoot: steps/
created_at: '2026-06-28T00:00:00+00:00'
updated_at: '2026-06-28T12:00:00+00:00'
steps:
- contract: contracts/security-scan/collect_security_manifest.yaml
- contract: contracts/security-scan/consensus_security_scan.yaml
- contract: contracts/security-scan/combine_security_findings.yaml
- contract: contracts/security-scan/generate_security_report.yaml
- contract: contracts/security-scan/validate_security_report.yaml
- contract: contracts/security-scan/finalize_security_report.yaml
