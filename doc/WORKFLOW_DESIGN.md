# Workflow Design

## Controller principle

The platform controls workflow. Qwen/OpenCode performs planning, implementation, testing, and review.

The platform should not:

- Hardcode domain task splitting
- Generate production code
- Materialize FILE blocks in real mode
- Apply edit_file/write_file JSON in real mode

## Adaptive Auto Workflow

Visible steps:

1. Generate Execution Prompts
2. Execute Prompts
3. AI Review + Validation

Step 1 creates `spec.md`, `task-manifest.json`, and task prompts. Python validates schema only.

Step 2 sends task prompts to the agent in the same session and checks that real project files changed.

Step 3 runs validation/test evidence first, then asks AI Review to return JSON PASS/FAIL.

## General Auto Development

Visible steps:

1. Plan Tasks
2. Execute Task Loop
3. Implementation Review
4. External Validation
5. Final Gate / Report

General is a fixed SOP flow. Task content is still AI-generated and schema-validated.


## Workflow Case Library

Reusable cases live under `tests/workflow_cases/`. Use them to preserve expected controller behavior when prompt templates or retry policy changes.

List/validate the case library:

```bash
python scripts/run_workflow_case_library.py --dry-run
```

Execute all cases in mock mode when you want a longer regression run:

```bash
python scripts/run_workflow_case_library.py --execute
```
