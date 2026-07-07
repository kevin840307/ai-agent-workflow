# Next Round Implementation

This round focuses on making the workflow controller easier to operate against real Qwen/OpenCode projects, especially when smaller models fail or need deterministic repair.

## Delivered Features

1. **Run Artifact Standardization**
   - Every completed workflow now writes a standard artifact index under `.workflow/artifacts/`.
   - The index includes console, step, diff, validation, patch, report, and metadata locations.
   - API: `GET /api/workflow-runs/{run_id}/artifact-index`.

2. **Workflow Runtime Module Facades**
   - Added focused runtime packages for execution, retry, validation, diff, patch, and observability.
   - These facades provide a migration path away from large runtime modules without breaking existing callers.

3. **Small Model Failure Repair Policy**
   - Added deterministic failure-to-repair mapping for common local-agent issues.
   - Examples: no file changes, invalid JSON/tool-call output, validation failure, test failure, timeout, and project guard errors.
   - API: `POST /api/small-model-repair-policy` and `GET /api/workflow-runs/{run_id}/repair-policy`.

4. **Real Agent Matrix v2**
   - Matrix planning now records agent, workflow, case, mode, command, output path, and execution result.
   - Supports plan, dry-run, and self-prompt-test mode.
   - CLI: `scripts/run_real_agent_matrix.py`.

5. **Run Detail UI**
   - Added a Run Detail tab that links console, diff, patch, artifact index, and repair policy.
   - Keeps the UI labels aligned with the previous request: `Profile` is used instead of `Model`, and the right-side tooling label is `Advanced`.

6. **Regression Test Framework Workflow**
   - Added `regression-test-case-generation` workflow.
   - It produces context, SOP definition SQL, runtime test data SQL, validation script, markdown case doc, dry-run report, and final gate artifacts.
   - E2E script: `scripts/run_regression_workflow_e2e.py`.

## Workflow Shape

```text
collect_context
→ generate_sop_sql
→ generate_runtime_sql
→ generate_validation
→ generate_case_doc
→ dry_run
→ final_gate
```

## Validation

The implementation is covered by targeted tests, E2E workflow scripts, and individual test-file execution for the whole collected test suite.
