id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: 'Adaptive loop: user request -> one agent generates the task-specific plan/files/tests -> isolated AI review -> optional external validation, retrying generation with concrete feedback.'
kind: custom
active: false
protected: false
deletable: true
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-04T00:00:00+08:00'
updated_at: '2026-07-04T00:00:00+08:00'
steps:
- contract: contracts/adaptive-auto-workflow/auto_generation.yaml
- contract: contracts/adaptive-auto-workflow/ai_review.yaml
- contract: contracts/adaptive-auto-workflow/run_external_validation.yaml
