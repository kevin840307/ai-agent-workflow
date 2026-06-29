# Testing Guide

## Daily / CI checks

Run these before every patch:

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

Run focused groups when debugging:

```powershell
python -m unittest tests.test_workflow_integration -v
python -m unittest tests.test_workflow_resilience_e2e -v
python -m unittest tests.test_workflow_non_e2e_contracts -v
python -m unittest tests.test_workflow_advanced_stability -v
python -m unittest tests.test_large_project_fixture -v
```

Expected default result includes skipped manual tests. Skips are intentional for checks that need real Qwen, Playwright, or a clean-repo subprocess smoke.

## Real Qwen checks

Minimal real Qwen CLI smoke:

```powershell
$env:RUN_REAL_QWEN="1"; $env:QWEN_USE_SERVE="0"; $env:QWEN_MOCK="0"
python -m unittest tests.test_workflow_advanced_stability.RealQwenSmokeTests -v
```

Full real Qwen system workflow smoke:

```powershell
$env:RUN_REAL_QWEN_FULL="1"; $env:QWEN_USE_SERVE="0"; $env:QWEN_MOCK="0"; $env:QWEN_TIMEOUT_SEC="300"
python -m unittest tests.test_real_qwen_workflow_manual.RealQwenFullWorkflowManualTests -v
```

Same-prompt real Qwen stability check:

```powershell
$env:RUN_REAL_QWEN_STABILITY="1"; $env:QWEN_USE_SERVE="0"; $env:QWEN_MOCK="0"; $env:REAL_QWEN_STABILITY_RUNS="3"
python -m unittest tests.test_real_qwen_workflow_manual.RealQwenStabilityManualTests -v
```

Clear PowerShell environment variables after manual checks:

```powershell
Remove-Item Env:RUN_REAL_QWEN -ErrorAction SilentlyContinue
Remove-Item Env:RUN_REAL_QWEN_FULL -ErrorAction SilentlyContinue
Remove-Item Env:RUN_REAL_QWEN_STABILITY -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_USE_SERVE -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_MOCK -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_TIMEOUT_SEC -ErrorAction SilentlyContinue
Remove-Item Env:REAL_QWEN_STABILITY_RUNS -ErrorAction SilentlyContinue
```


Bash / Git Bash equivalents:

```bash
RUN_REAL_QWEN=1 QWEN_USE_SERVE=0 QWEN_MOCK=0 python -m unittest tests.test_workflow_advanced_stability.RealQwenSmokeTests -v
RUN_REAL_QWEN_FULL=1 QWEN_USE_SERVE=0 QWEN_MOCK=0 QWEN_TIMEOUT_SEC=300 python -m unittest tests.test_real_qwen_workflow_manual.RealQwenFullWorkflowManualTests -v
RUN_REAL_QWEN_STABILITY=1 QWEN_USE_SERVE=0 QWEN_MOCK=0 REAL_QWEN_STABILITY_RUNS=3 python -m unittest tests.test_real_qwen_workflow_manual.RealQwenStabilityManualTests -v
RUN_CLEAN_REPO_SMOKE=1 python -m unittest tests.test_release_and_ui_manual.CleanRepoPatchApplyManualTests -v
RUN_PLAYWRIGHT_UI=1 QWEN_MOCK=1 QWEN_USE_SERVE=0 python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests -v
```

## Clean repo smoke

Copies the repo to a temporary folder and runs compile + a focused contract suite there:

```powershell
$env:RUN_CLEAN_REPO_SMOKE="1"
python -m unittest tests.test_release_and_ui_manual.CleanRepoPatchApplyManualTests -v
```

## Playwright UI E2E

Install Playwright once:

```powershell
python -m pip install playwright
python -m playwright install chromium
```

Run the opt-in UI E2E:

```powershell
$env:RUN_PLAYWRIGHT_UI="1"; $env:QWEN_MOCK="1"; $env:QWEN_USE_SERVE="0"
python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests -v
```

The Playwright check waits for `domcontentloaded` and visible UI selectors instead of `networkidle`. Do not use `networkidle` here because the app may keep background requests or event streams alive while the workflow UI is active. It also checks the project directory by basename because the UI may display Windows home paths as `~` instead of the full `C:\Users\...` path.
It also creates a unique project title and verifies the project list before asserting the active session header, so existing local store data will not cause false failures.

## Optional frontend syntax check

```powershell
Get-Content -Raw static\js\main.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-runner.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\controller.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\layout-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\step-settings-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\template-editor.js | node --input-type=module --check
```


## Playwright UI E2E path assertion note

The UI may shorten a Windows home path such as `C:\Users\name\...` to `~/...` in `#runMeta`.
The Playwright test therefore validates only the generated temporary project folder name, for example
`qwen-ui-e2e-xxxx`, instead of comparing the full absolute path.

If a failure still expects the full `C:\Users\...` path, the latest `tests/test_release_and_ui_manual.py`
was not applied. Confirm that the file contains `run_meta_text = run_meta.inner_text(...)`.

## Extra workflow quality contracts

These run by default and cover API response schema, run-log observability, broad performance baselines, and fuzzed file-boundary security:

```powershell
python -m unittest tests.test_workflow_quality_contracts -v
```

They are included in:

```powershell
python -m unittest discover -s tests -v
```

## Playwright UI behavior regression suite

`PlaywrightUiManualTests` now covers these browser flows:

- basic create project -> run workflow -> reset
- reset must not create duplicate project rows
- workflow preview shows full description/steps before a run, compacts after a run, and expands again after switching workflow
- intentional final review failure -> UI retry -> workflow passes
- intentional generated-test-file validation failure -> failed step/error is visible and retry is enabled

Run all UI behavior tests:

```powershell
$env:RUN_PLAYWRIGHT_UI="1"; $env:QWEN_MOCK="1"; $env:QWEN_USE_SERVE="0"
python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests -v
```

Run focused UI tests:

```powershell
$env:RUN_PLAYWRIGHT_UI="1"; $env:QWEN_MOCK="1"; $env:QWEN_USE_SERVE="0"
python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests.test_playwright_reset_and_preview_regression_is_opt_in -v
python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests.test_playwright_retry_failed_review_is_opt_in -v
python -m unittest tests.test_release_and_ui_manual.PlaywrightUiManualTests.test_playwright_gate_failed_ui_is_opt_in -v
```

The failed-review and gate-failure UI checks use deterministic mock scenarios internally:

```powershell
$env:QWEN_MOCK_SCENARIO="fail_final_review_once"
$env:QWEN_MOCK_SCENARIO="generate_tests_no_files"
```

You normally do not need to set `QWEN_MOCK_SCENARIO` yourself because the Playwright test starts its own server subprocess with the correct scenario.

Clear optional Playwright variables after manual checks:

```powershell
Remove-Item Env:RUN_PLAYWRIGHT_UI -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_MOCK_SCENARIO -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_MOCK -ErrorAction SilentlyContinue
Remove-Item Env:QWEN_USE_SERVE -ErrorAction SilentlyContinue
```

Plain marker names for documentation contract tests:

```text
QWEN_MOCK_SCENARIO=fail_final_review_once
QWEN_MOCK_SCENARIO=generate_tests_no_files
```
