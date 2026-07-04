id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: 'Simple automatic loop: user request -> auto TODO files -> do task -> N sub-agent review -> retry do task on review/test/validation failure -> final evidence gate.'
kind: custom
active: false
protected: false
deletable: true
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-04T00:00:00+08:00'
updated_at: '2026-07-04T00:00:00+08:00'
steps:
- contract: contracts/adaptive-auto-workflow/prepare_project.yaml
- contract: contracts/adaptive-auto-workflow/plan_tasks.yaml
- contract: contracts/adaptive-auto-workflow/implementation_review.yaml
- contract: contracts/adaptive-auto-workflow/build.yaml
- contract: contracts/adaptive-auto-workflow/sub_agent_review.yaml
- contract: contracts/adaptive-auto-workflow/generate_tests.yaml
- contract: contracts/adaptive-auto-workflow/run_test.yaml
- contract: contracts/adaptive-auto-workflow/run_external_validation.yaml
- contract: contracts/adaptive-auto-workflow/final_review.yaml
- contract: contracts/adaptive-auto-workflow/final_gate.yaml
