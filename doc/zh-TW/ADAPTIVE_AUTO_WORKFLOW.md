# Adaptive Auto Workflow

Adaptive Auto Workflow 是簡化版自動開發流程，適合使用者只提供一段需求，系統就自動產生、review、驗證，失敗後再回修。

## 流程

```text
需求
  -> Step 1: Auto Generation
  -> Step 2: AI Review
  -> Step 3: Run External Validation optional
  -> review / validation 失敗時，把錯誤訊息回到 Step 1 修復
```

## Step 1: Auto Generation

Agent 讀取使用者需求與 selected project，並把需要的 production files、tests 或文件實際寫入 selected Project Path。

## Step 2: AI Review

使用 reviewer session 檢查 Step 1 的產物。若 review 失敗，會把 feedback 回灌到 Step 1 進行 repair。

## Step 3: Run External Validation

此步驟使用共用的 `run_external_validation` Python function。

行為：

- Validation Script 空白：跳過外部驗證，直接回傳 `Status: PASS`。
- 有填 Python Validation Script：執行該 script。
- Exit code 非 0：stdout、stderr、exit code 寫入 `external-validation-result.md`，並把錯誤訊息回到 Step 1。

## Validation Script 範例

相對路徑：

```text
tools/validate_config.py
```

絕對路徑：

```text
C:\work\validators\validate_config.py
```

Runner 會先嘗試：

```text
python <script> --project <project_path> --workspace <run_workspace> --output <output_dir>
```

如果 script 不支援這些參數，會 fallback 成：

```text
python <script>
```
