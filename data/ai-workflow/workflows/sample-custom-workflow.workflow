id: sample-custom-workflow
name: Sample Custom Workflow
description: Editable example copied from the system workflow. Use it to learn how
  steps, validators, review, retry, and gates are configured.
kind: custom
active: false
protected: false
deletable: true
skillRoot: ~/.qwen/skills
promptRoot: steps/
created_at: '2026-06-27T13:47:47.304379+00:00'
updated_at: '2026-06-27T13:47:47.304379+00:00'
steps:
- contract: contracts/sample-custom-workflow/prepare_project.yaml
- contract: contracts/sample-custom-workflow/generate_spec.yaml
- contract: contracts/sample-custom-workflow/validate_spec.yaml
- contract: contracts/sample-custom-workflow/review_spec.yaml
- contract: contracts/sample-custom-workflow/spec_gate.yaml
- contract: contracts/sample-custom-workflow/generate_todo.yaml
- contract: contracts/sample-custom-workflow/validate_todo.yaml
- contract: contracts/sample-custom-workflow/review_todo.yaml
- contract: contracts/sample-custom-workflow/todo_gate.yaml
- contract: contracts/sample-custom-workflow/generate_tests.yaml
- contract: contracts/sample-custom-workflow/build.yaml
- contract: contracts/sample-custom-workflow/run_test.yaml
- contract: contracts/sample-custom-workflow/final_review.yaml
- contract: contracts/sample-custom-workflow/final_gate.yaml
