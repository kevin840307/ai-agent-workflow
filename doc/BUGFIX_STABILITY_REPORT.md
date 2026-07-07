# Bugfix / Stability / Layout Cleanup Report

## Scope

Base package: `ai-workflow-2and4-updated.zip`

Goal: find real bugs, improve system stability, and clean up abnormal UI/layout issues without adding large new product features.

## Bugs / Stability Issues Fixed

### 1. UI controls referenced by JavaScript were not registered

`static/js/core/dom.js` was missing DOM key registrations used by the workflow UI:

- `advancedMode`
- `runProfile`
- `runResultPanel`
- `runDetail`
- `stepDetails`

Impact: some Advanced/Profile/Run Detail/Step Details UI behaviors could silently fail because `ui.byKey(...)` could not resolve the element.

Fix: added the missing keys and added a static architecture contract test that scans JS `ui.byKey("...")` references and verifies every key is registered.

### 2. Details tab layout was outdated

The UI now has 5 tabs:

- Steps
- Agent
- Logs
- Artifacts
- Run Detail

But CSS still used a 4-column grid.

Fix: changed the tab grid to 5 columns and added a small-screen fallback so tabs wrap cleanly on narrow screens.

### 3. Undefined CSS token caused weak/broken borders

CSS referenced `var(--border)`, but the token file uses `--line`. This could cause borders around profile/advanced controls to disappear or render inconsistently.

Fix: replaced `var(--border)` usage with `var(--line)` and added a regression test.

### 4. Run Detail layout overflow hardening

Long run IDs, paths, error messages, and artifact paths could stretch the panel horizontally or make cards look broken.

Fix: added Run Detail overflow handling:

- `min-width: 0`
- `overflow-wrap: anywhere`
- action button wrapping
- better responsive behavior for run detail cards

### 5. Dead-owner active run could block a project after process interruption

A run may remain in an active state if the worker process is killed/interrupted. The project lock could then block new runs even though no owner process is alive.

Fix: added stale active-run recovery:

- detect inactive/dead owner process
- mark stale active run as `failed`
- set `error_code=INTERRUPTED`
- mark `restart_recoverable=true`
- clear project run lock
- write recovery state/log/artifacts

### 6. Replay could accidentally use isolated workspace path instead of original project path

When patch/dry-run isolation is used, replay could inherit the isolated workspace path from the source run.

Fix: replay now prefers `original_project_path` and also preserves important run metadata such as timeout, patch mode, versions, and context pack.

## New/Updated Tests

- `tests/test_static_architecture_contract.py`
  - validates all `ui.byKey(...)` references have matching `UI.ids` entries
  - validates tab layout and CSS token regressions

- `tests/test_test_pipeline_and_lifecycle.py`
  - validates stale/dead-owner active run recovery
  - validates active run is marked interrupted and project is no longer blocked

## Static Checks

```text
python -m compileall app tests scripts -q
COMPILE_EXIT:0
```

```text
node --check static/js/**/*.js
NODE_CHECK_EXIT:0
```

```text
CSS brace balance check
CSS_CHECK_EXIT:0
```

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest --collect-only -q
306 tests collected
```

## Targeted Tests

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_static_architecture_contract.py \
  tests/test_test_pipeline_and_lifecycle.py -q

24 passed, 2 warnings, 56 subtests passed
```

## Full Test Matrix

The project's production test gate is the grouped CI matrix. Running all workflow/TestClient/E2E tests in a single long Python process can still be unreliable in constrained environments, so each group was executed independently.

```text
A_core_cli_api: 46 passed, 24 subtests passed
B_general_project_prompt: 32 passed
C_productization_features: 21 passed
D_manual_run_state: 7 passed, 7 skipped, 18 subtests passed
E_runtime_safety_contracts: 76 passed, 92 subtests passed
F_workflow_assets_stability: 27 passed, 1 skipped, 8 subtests passed
G_self_prompt_e2e: 1 passed
H_workflow_core_contracts: 29 passed, 18 skipped, 4 subtests passed
I_workflow_integration: 2 passed
J_workflow_quality_resilience: 39 passed, 76 subtests passed
```

Total:

```text
280 passed
26 skipped
222 subtests passed
0 failed
```

Note: `python scripts/run_tests.py --mode all --execute-all` was started but the combined command exceeded the tool/session timeout after early groups. Each group was then run independently and passed.

## E2E Results

### Self-prompt sorting workflow

Prompt:

```text
幫我用python寫氣泡排序法+選擇排序法+插入排序法+快速排序法+合併排序法+堆積排序法+希爾排序法
```

Result:

```text
general-auto-development: PASS, stability 100/100, retry_total 0
adaptive-auto-workflow: PASS, stability 100/100, retry_total 0
```

### General Auto Development E2E

```text
01-normal-no-validation: done
02-execute-no-files-retry: done
03-review-fail-repair: done
04-validation-fail-repair: done
status: PASS
```

### Adaptive Auto Workflow E2E

```text
01-normal-pass: done
02-execute-no-files-retry: done
03-review-fail-repair: done
04-validation-fail-repair: done
status: PASS
```

### Regression Test Framework workflow E2E

```text
workflow: regression-test-case-generation
steps_passed: 7/7
retry_total: 0
status: PASS
artifact_schema: aiwf.run-artifacts.v1
repair_policy_schema: aiwf.small-model-repair-policy.v1
```

## Remaining Notes

- Visual browser screenshot testing was not completed in this container because the Playwright browser binary is not installed. Static JS/CSS/DOM contract checks passed instead.
- The grouped CI matrix is the recommended production test gate for this project.
