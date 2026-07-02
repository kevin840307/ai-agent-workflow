id: general-auto-development
name: General Auto Development
description: Read the selected project, plan a small task breakdown, generate focused
  tests, build inside the project only, run tests, and require the project validation.py
  script before final review.
kind: custom
active: false
protected: false
deletable: true
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-02T00:00:00+08:00'
updated_at: '2026-07-02T15:04:15.925153+00:00'
steps:
- contract: contracts/general-auto-development/prepare_project.yaml
- contract: contracts/general-auto-development/plan_tasks.yaml
- contract: contracts/general-auto-development/implementation_review.yaml
- contract: contracts/general-auto-development/generate_tests.yaml
- contract: contracts/general-auto-development/build.yaml
- contract: contracts/general-auto-development/run_test.yaml
- contract: contracts/general-auto-development/run_external_validation.yaml
- contract: contracts/general-auto-development/final_review.yaml
- contract: contracts/general-auto-development/final_gate.yaml
