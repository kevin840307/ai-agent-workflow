id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: 'Adaptive loop: generate task prompts -> execute task prompt loop -> isolated AI review -> optional external validation, retrying generation with concrete feedback.'
kind: system
active: true
protected: true
deletable: false
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-04T00:00:00+08:00'
updated_at: '2026-07-04T00:00:00+08:00'
steps:
- contract: contracts/adaptive-auto-workflow/generate_task_prompts.yaml
- contract: contracts/adaptive-auto-workflow/auto_generation.yaml
- contract: contracts/adaptive-auto-workflow/ai_review.yaml
- contract: contracts/adaptive-auto-workflow/run_external_validation.yaml
