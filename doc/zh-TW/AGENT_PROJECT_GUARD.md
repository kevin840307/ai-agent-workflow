# Agent 專案限制設定

AI Workflow 現在會在 agent 執行前，自動準備專案層級的 Qwen / OpenCode guard 設定：

```text
<project>/.qwen/settings.json
<project>/.qwen/QWEN.md
<project>/opencode.json
```

目標是讓 Qwen / OpenCode 使用它們自己的 edit / write 工具直接修改檔案，同時限制只能寫入目前選擇的 Project Path。

## 策略

- 讀取策略：不限制。Agent 需要外部資料作為 context 時，可以讀取其它位置。
- 寫入策略：只允許目前專案。Agent 只能在 selected Project Path 內建立、修改、刪除或重新命名檔案。
- 危險操作會透過設定與 prompt guardrail 阻擋。
- 平台管理的 guard 檔案不可被 agent 修改：`.qwen/**`、`opencode.json`、`.ai-workflow/**`、`.qwen-workflow/**`、`.git/**`。

## Qwen Code

AI Workflow 會寫入 `.qwen/settings.json`，並設定 `tools.approvalMode = auto-edit`，讓 Qwen 可以使用檔案編輯工具，但不使用 YOLO 模式。平台也會寫入 `.qwen/QWEN.md`，提供專案層級的限制規則。

Qwen 從專案 root 執行時會讀取 `.qwen/settings.json`。Qwen 也支援 `tools.sandbox`，但目前預設不開啟，因為需求是「讀取其它地方不限制」。

## OpenCode

AI Workflow 會寫入 `opencode.json`，主要權限如下：

- `edit`：允許一般 project-relative 編輯，拒絕常見逃逸路徑與 guard 檔案。
- `external_directory`：允許，讓外部讀取仍可使用。
- `bash`：預設拒絕，只允許少量無害的查詢 / 狀態指令。
- `webfetch`、`websearch`、`task`：拒絕。

OpenCode 使用 `edit` 權限管理所有檔案修改，包含 edit / write / apply_patch；當工具碰到目前工作目錄外的路徑時，會經過 `external_directory` 權限。

## Runtime 檢查

Build / Generate Tests / Adaptive Auto Generation 執行後，AI Workflow 會比較 agent 執行前後的專案檔案快照。

如果 Qwen / OpenCode 直接修改了合法的專案檔案，runtime 會接受這些修改，並把實際變更檔案記錄成 step artifact。對所有真實 workflow 執行而言，Build / Auto Generation / Generate Tests 都是 direct-edit-only：平台不再替 agent materialize platform file blocks。Mock mode 仍可在自動化測試中模擬 direct edits。

這不是 OS sandbox。CLI config 是第一層保護；AI Workflow 仍保留自己的 path guard 與執行後 project diff 驗證。
