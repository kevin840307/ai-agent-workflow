id: system-controlled-qwen
name: Controlled Qwen Workflow
description: Built-in protected workflow. Duplicate it to create an editable custom
  workflow.
kind: system
active: true
protected: true
deletable: false
skillRoot: ~/.qwen/skills
promptRoot: steps/
created_at: null
updated_at: null
steps:
- contract: contracts/system-controlled-qwen/prepare_project.yaml
- contract: contracts/system-controlled-qwen/reason_requirement.yaml
- contract: contracts/system-controlled-qwen/generate_spec.yaml
- contract: contracts/system-controlled-qwen/validate_spec.yaml
- contract: contracts/system-controlled-qwen/review_spec.yaml
- contract: contracts/system-controlled-qwen/spec_gate.yaml
- contract: contracts/system-controlled-qwen/generate_todo.yaml
- contract: contracts/system-controlled-qwen/validate_todo.yaml
- contract: contracts/system-controlled-qwen/review_todo.yaml
- contract: contracts/system-controlled-qwen/todo_gate.yaml
- contract: contracts/system-controlled-qwen/generate_tests.yaml
- contract: contracts/system-controlled-qwen/reason_build.yaml
- contract: contracts/system-controlled-qwen/build.yaml
- contract: contracts/system-controlled-qwen/run_test.yaml
- contract: contracts/system-controlled-qwen/final_review.yaml
- contract: contracts/system-controlled-qwen/final_gate.yaml
