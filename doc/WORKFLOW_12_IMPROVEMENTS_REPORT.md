# Workflow 12 Improvements Report

This report records the stabilization work added for General Auto Development and Adaptive Auto Workflow.

## Project understanding

The project is a FastAPI workflow controller. Python owns workflow state, retry, gates, validation, file extraction, project safety, and logs. Qwen/OpenCode are treated as agent workers that receive bounded prompts and produce project changes or artifacts. Workflows are configured under `data/ai-workflow/workflows`, step contracts live under `data/ai-workflow/contracts`, and runtime execution is handled by `app/workflow_runtime` plus `app/runtime_modules`.

## Implemented items

1. **General workflow contract aligned with documentation**
   - `general-auto-development` now uses an evidence-based SOP: `plan_tasks -> build -> generate_tests -> run_test -> implementation_review -> run_external_validation -> final_review -> final_gate`.

2. **Workflow stability scoring**
   - Added `app/workflow_runtime/stability_score.py`.
   - Self-prompt E2E writes `stability-report.md` with score, risk, retry total, and findings.

3. **Failure scenario E2E coverage**
   - General and Adaptive E2E runners exercise normal pass, no-files retry, review-fail repair, and validation-fail repair scenarios.

4. **Clear workflow positioning**
   - Documentation now states General Auto Development is for deterministic SOP coding with tests/validation.
   - Adaptive Auto Workflow is for generated task prompts plus review/validation.

5. **Run profile retry policy**
   - Added `strict` and `debug` run profile support.
   - `debug` can intentionally preserve high retry limits; normal use is capped.

6. **Deterministic validation beats AI self-review**
   - `final_review` is now a Python validation gate using `validate_general_auto_final`.
   - AI review can surface risk, but Python test/validation evidence decides the final pass condition.

7. **Runtime modularization started**
   - Stability scoring and isolated workspace behavior are split into focused runtime/security modules.
   - This reduces future changes inside the large `actions.py` controller surface.

8. **Project isolation helper**
   - Added `app/security/isolated_workspace.py` to copy a project into an isolated workspace, calculate changed files, and apply validated changes back.

9. **Real-agent smoke direction preserved**
   - `doc/REAL_AGENT_SMOKE.md` remains the documented bridge for running true Qwen/OpenCode smoke tests after deterministic self-prompt E2E is stable.

10. **Failure observability and replay artifacts**
    - E2E logs export run JSON, timeline, steps, project snapshots, validation output, and stability report.

11. **Validation script as first-class contract**
    - Documentation clarifies validation script behavior, fallback, command arguments, stdout/stderr, and deterministic precedence.

12. **Workflow case library direction**
    - Self-prompt sorting case now acts as a reusable benchmark case for General and Adaptive workflows.

## Executed verification

- `python -m compileall app tests scripts -q`
- `python -m pytest --collect-only -q` collected 282 tests.
- Test groups executed and passed across all `tests/test_*.py` files.
- Self-prompt sorting E2E executed both workflows with stability score `100/100`.
- General E2E executed 4 scenarios and passed.
- Adaptive E2E executed 4 scenarios and passed.

See exported logs for the exact command output and workflow run artifacts.
