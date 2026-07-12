# Workflow 與 Asset 開發

## Asset 結構

```text
data/ai-workflow/
  workflows/*.workflow
  contracts/<workflow>/*.yaml
  steps/<workflow>/*.md
  functions/<workflow>/*.py
```

專案覆寫位於 `<project>/.ai-workflow/`，優先於全域 Asset。

## 設計原則

- Prompt 只指示 Qwen／OpenCode，不包含平台要代寫的使用者檔案。
- Python Function 只做驗證、路由、摘要、保護，不實作使用者要求的產品功能。
- Contract 宣告 Timeout、Retry、Recovery Budget、Review、Validation、Artifact。
- Task Prompt 要短且自然，不可輸出 Shell Script、絕對路徑、Code Block、FILE Block 或 Tool-call JSON。
- 每個新的 Failure Route／Completion Rule 都要有確定性測試。

## Recovery Budget 範例

```yaml
maxRetries: 99
recoveryBudget:
  maxRunFailures: 40
  maxStepFailures: 24
  maxTaskFailures: 12
  maxFailureClass: 12
  maxFingerprint: 9
  wallClockMinutes: 60
  freshSessionEvery: 3
```

高 `maxRetries` 保留小模型修復機會；累積 Budget 防止無限空轉。

## Task Acceptance 範例

```json
{
  "id": "TASK-001",
  "title": "更新設定載入",
  "kind": "implementation",
  "prompt": "更新現有設定載入器並保留公開行為。",
  "acceptance": ["既有與新增測試通過"],
  "scope": ["src/config/**", "tests/config/**"],
  "mustNotChange": ["validation.py"],
  "dependencies": [],
  "risk": "normal"
}
```

只有專案證據支持時才加入路徑限制，平台不可自行猜測。
