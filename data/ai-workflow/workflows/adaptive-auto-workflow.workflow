id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: Route a user request, normalize explicit user/workflow-md instructions, compile a task workflow instance, run small-task development loops, and verify completion with tests plus optional user Python acceptance.
folderName: general-auto-development
kind: custom
active: false
protected: false
deletable: true
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-04T00:00:00+08:00'
updated_at: '2026-07-04T00:00:00+08:00'
steps:
- contract: contracts/general-auto-development/prepare_project.yaml
- contract: contracts/general-auto-development/plan_tasks.yaml
- contract: contracts/general-auto-development/implementation_review.yaml
- contract: contracts/general-auto-development/build.yaml
- contract: contracts/general-auto-development/generate_tests.yaml
- contract: contracts/general-auto-development/run_test.yaml
- contract: contracts/general-auto-development/run_external_validation.yaml
- contract: contracts/general-auto-development/final_review.yaml
- contract: contracts/general-auto-development/diff_review.yaml
- contract: contracts/general-auto-development/final_gate.yaml
