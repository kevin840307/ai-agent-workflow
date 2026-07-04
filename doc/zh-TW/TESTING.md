# 測試指南

## 日常 / CI 檢查

每次修改前後建議執行：

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

Debug 特定區塊時可執行：

```powershell
python -m unittest tests.test_workflow_integration -v
python -m unittest tests.test_workflow_resilience_e2e -v
python -m unittest tests.test_workflow_non_e2e_contracts -v
python -m unittest tests.test_workflow_advanced_stability -v
python -m unittest tests.test_large_project_fixture -v
```

預設測試會 skip 需要真實 Qwen、Playwright 或 clean repo subprocess 的手動情境，這是正常行為。

## 一次執行 8 個 opt-in 實際情境

PowerShell：

```powershell
$env:RUN_REAL_QWEN="1"; $env:RUN_REAL_QWEN_FULL="1"; $env:RUN_REAL_QWEN_STABILITY="1"; $env:RUN_CLEAN_REPO_SMOKE="1"; $env:RUN_PLAYWRIGHT_UI="1"; $env:QWEN_USE_SERVE="0"; $env:QWEN_MOCK="0"; $env:QWEN_TIMEOUT_SEC="300"; $env:REAL_QWEN_STABILITY_RUNS="3"
python -m unittest tests.test_workflow_advanced_stability.RealQwenSmokeTests tests.test_real_qwen_workflow_manual.RealQwenFullWorkflowManualTests tests.test_real_qwen_workflow_manual.RealQwenStabilityManualTests tests.test_release_and_ui_manual.CleanRepoPatchApplyManualTests tests.test_release_and_ui_manual.PlaywrightUiManualTests -v
```

清除 PowerShell 環境變數：

```powershell
Remove-Item Env:RUN_REAL_QWEN -ErrorAction SilentlyContinue
Remove-Item Env:RUN_REAL_QWEN_FULL -ErrorAction SilentlyContinue
Remove-Item Env:RUN_REAL_QWEN_STABILITY -ErrorAction SilentlyContinue
Remove-Item Env:RUN_CLEAN_REPO_SMOKE -ErrorAction SilentlyContinue
Remove-Item Env:RUN_PLAYWRIGHT_UI -ErrorAction SilentlyContinue
```

Linux / macOS：

```bash
RUN_REAL_QWEN=1 RUN_REAL_QWEN_FULL=1 RUN_REAL_QWEN_STABILITY=1 RUN_CLEAN_REPO_SMOKE=1 RUN_PLAYWRIGHT_UI=1 QWEN_USE_SERVE=0 QWEN_MOCK=0 QWEN_TIMEOUT_SEC=300 REAL_QWEN_STABILITY_RUNS=3 \
python -m unittest tests.test_workflow_advanced_stability.RealQwenSmokeTests tests.test_real_qwen_workflow_manual.RealQwenFullWorkflowManualTests tests.test_real_qwen_workflow_manual.RealQwenStabilityManualTests tests.test_release_and_ui_manual.CleanRepoPatchApplyManualTests tests.test_release_and_ui_manual.PlaywrightUiManualTests -v
```

清除：

```bash
unset RUN_REAL_QWEN RUN_REAL_QWEN_FULL RUN_REAL_QWEN_STABILITY RUN_CLEAN_REPO_SMOKE RUN_PLAYWRIGHT_UI
```

## Mock 情境

```powershell
$env:QWEN_MOCK="1"
$env:QWEN_MOCK_SCENARIO="fail_final_review_once"
python -m unittest tests.test_workflow_advanced_stability -v
```

```powershell
$env:QWEN_MOCK_SCENARIO="generate_tests_no_files"
python -m unittest tests.test_workflow_resilience_e2e -v
```
