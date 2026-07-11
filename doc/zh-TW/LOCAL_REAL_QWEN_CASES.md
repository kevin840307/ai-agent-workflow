# 本機真實 Qwen Case Library

這組 Case 用來驗證真正的 Qwen CLI、Workflow Retry、Project Path、測試與使用者驗證，不使用 Mock Agent。

每個 Case 都只有一行使用者 Prompt，最後一定會另外執行 `validation.py` 確認結果，不能只相信 Agent 回覆成功。

## Case 內容

| Case | 目的 |
|---|---|
| `bubble_sort_new` | 新增單檔功能、不可修改輸入 |
| `fix_existing_sort_bug` | 修正既有 Production Bug |
| `root_pytest_update` | 沿用根目錄 `test_*.py`，避免重複測試檔 |
| `json_config_loader` | 新增檔案讀取與例外處理 |
| `csv_summary` | 新增資料處理功能 |
| `repair_validation_failure` | 修正會讓 Required Validation 失敗的既有程式 |

## 先查看 Prompt

```powershell
python .\scripts\run_local_qwen_cases.py --list
```

## Dry Run

不啟動 Qwen，只建立每個 Case 的執行計畫：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 -DryRun
```

## 執行一個 Qwen Case

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 `
  -Case bubble_sort_new `
  -Agent qwen `
  -Workflow general-auto-development
```

## 執行全部 Case

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 `
  -Case all `
  -Agent qwen `
  -Workflow general-auto-development `
  -TimeoutSec 900
```

## 重複跑穩定性測試

以下會讓每個 Case 各跑 5 次：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 `
  -Case all `
  -Repeat 5 `
  -Output reports\qwen-stability-5x
```

## 使用 Adaptive 比較

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 `
  -Case all `
  -Workflow adaptive-auto-workflow `
  -Output reports\qwen-adaptive
```

## 結果

每個 Case 會產生：

```text
reports/local-real-agent-cases/<case>/
├── project/                 # 最後的實際專案
├── plan.json                # 單行 Prompt 與執行命令
├── run.json                 # Controller 最終 Run 狀態
├── validation-result.json   # validation.py 真實 Exit Code
├── stdout.log
├── stderr.log
└── summary.json
```

整批結果：

```text
reports/local-real-agent-cases/summary.json
reports/local-real-agent-cases/report.md
```

判定 PASS 必須同時符合：

1. Controller CLI 正常結束。
2. Workflow 最終狀態為 `done`。
3. `validation.py` 再次獨立執行且 Exit Code 為 0。
4. Case 宣告的必要檔案存在。

## 執行前確認

```powershell
qwen --version
```

並確認本機模型、Context Window 與 Qwen Tool Calling 已正確設定。若環境仍有：

```powershell
$env:QWEN_MOCK = "1"
```

請先移除：

```powershell
Remove-Item Env:QWEN_MOCK -ErrorAction SilentlyContinue
```
