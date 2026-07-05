id: general-auto-development
name: General Auto Development
description: 'Fixed SOP development controller: AI plans SPEC/TODO/task prompts, controller executes the task loop in one CLI session, AI reviews implementation, Python validation runs when provided, then final gate checks completion.'
kind: system
active: true
protected: true
deletable: false
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-02T00:00:00+08:00'
updated_at: '2026-07-05T00:00:00+08:00'
steps:
- contract: contracts/general-auto-development/plan_tasks.yaml
- contract: contracts/general-auto-development/build.yaml
- contract: contracts/general-auto-development/implementation_review.yaml
- contract: contracts/general-auto-development/run_external_validation.yaml
- contract: contracts/general-auto-development/final_gate.yaml
