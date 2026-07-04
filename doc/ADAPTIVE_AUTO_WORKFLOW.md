# Adaptive Auto Workflow

Adaptive Auto Workflow 是簡化版自動開發流程，目標是讓使用者只輸入需求，就能自動完成：

```text
需求 -> 產生 / 修改檔案 -> AI Review -> 外部驗證 optional -> 失敗回修
```

## Flow

```text
Step 1: Auto Generation
  - 讀取使用者需求與專案內容
  - 自動產生 task plan / production files / tests / 文件
  - 必須把檔案實際寫入 selected Project Path

Step 2: AI Review
  - 使用獨立 reviewer session 檢查 Step 1 產物
  - 發現問題時，錯誤訊息回到 Step 1 修復

Step 3: Run External Validation
  - 使用共用 Python Function：run_external_validation
  - 未輸入 validation_script：跳過並產生 Status: PASS
  - 有輸入 validation_script：執行該 Python script
  - 驗證失敗：把錯誤訊息回到 Step 1 repair
```

## Validation Script 規則

### 未輸入

不執行任何外部驗證，artifact 會顯示 PASS / skipped。

### 有輸入

支援相對路徑或絕對路徑：

```text
tools/validate_config.py
C:\work\validators\validate_config.py
```

Runner 會先嘗試：

```text
python <script> --project <project_path> --workspace <workspace> --output <output_dir>
```

如果 script 不支援參數，會自動 fallback：

```text
python <script>
```

### 失敗行為

當 script exit code 非 0：

1. 寫入 `external-validation-result.md`
2. 保留 stdout / stderr / exit code
3. workflow 標記該 step failed
4. retry target 回到 `auto_generation`
5. 將錯誤訊息注入 repair prompt

## Contract 重點

```yaml
key: run_external_validation
type: python
function: run_external_validation
requiresValidationScript: false
fallbackValidationScripts: []
retryFromStepKey: auto_generation
injectFailureFeedback: true
```

`requiresValidationScript: false` 是刻意設計，代表使用者可以不填 validation script；不填時流程仍可完成。
