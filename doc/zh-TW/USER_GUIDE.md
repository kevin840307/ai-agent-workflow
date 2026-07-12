# 使用者操作手冊

## Simple Mode

Simple Mode 是一般使用者的預設畫面，且預設採無人值守執行。

```text
選擇專案 → 輸入一句需求 → 開始
→ 平台自動理解、修改、驗證、修復與恢復
→ 查看單一且可理解的結果
```

主畫面只顯示：

- 目前 Autopilot 階段；
- 已完成與正在執行的任務；
- 模型已連線、離線重試中或待確認；
- 精簡結果摘要；
- 變更摘要、Patch Review 與驗證 Evidence 入口。

一般使用者不需要理解 Session ID、Retry Fingerprint、Task Manifest、Provider Queue 或原始 Event。


### Patch Review 與執行產物

- Run Center 不再提供獨立「變更」Tab；總覽顯示變更摘要並開啟唯一的 Patch Review Workbench。
- Workbench 提供檔案搜尋／篩選、可拖曳且會記住寬度／收合狀態的側欄、Unified／Split、專注模式、字體縮放、獨立捲動，以及大型 Diff 分段載入。
- 「拒絕並要求修正」、「僅核准」、「核准並套用」是三個不同操作。Approval 綁定 Patch、檔案選擇與 Validation Evidence Hash，內容改變即失效。
- Partial Patch 必須在隔離工作區重新組合與執行 Required Validation；無人值守只允許完整 Patch。
- 「技術檔案」改名「執行產物」。Artifact 類型、重要性、排序、來源、媒體類型與預覽模式只讀取明確 Metadata／契約；舊 Run 第一次開啟時會補建一次，仍無 Metadata 的資料顯示「未分類」，不得由檔名／路徑猜測。
- Step 的「對應文件」會開啟獨立且只屬於該 Step 的預覽 Dialog，只包含該 Step 的 Prompt、明確輸出、依賴與 Evidence，不會跳到全域執行產物。

## Advanced Mode

進階模式才顯示 Workflow／Profile／Thinking、無人值守開關、Project Validation Profile 編輯、Validation Script、Session、Checkpoint、Retry History、Artifact、Patch Review、修復策略及 Run 比較。

Simple／Advanced 共用同一份狀態與 Workflow Kernel，只是顯示層級不同，不會維護兩套流程。

## Project Validation Profile

Profile 由 Controller 依 Project Path 保存並重用，包含驗證階段、Baseline／Fast／Full 分類、環境需求、Artifact，以及可選 Scope Policy。

| 狀態 | 意義 |
|---|---|
| `Draft` | 已偵測或編輯，尚未實際證明 |
| `Verified` | 至少成功執行一次 |
| `Trusted` | 至少成功驗證三次 |
| `Stale` | Build／Test／Validation 描述檔已變更 |

編輯後會回到 Draft；Stale 必須重新驗證後才適合無人值守交付。

## 無人值守流程

```text
理解專案
→ 環境 Preflight
→ Baseline 驗證
→ Task Contract
→ Checkpoint／隔離工作區
→ Agent 實作
→ Focused Validation
→ 依進展自動修復
→ Full Validation 與不可變更 Validation Script
→ 原子套用與套用後驗證
```

Controller 重啟後，平台會辨識可安全恢復的無人值守 Run，從持久化狀態繼續。模型 Endpoint 暫時關閉時，Run 會低頻等待模型回線，不會快速消耗 Retry；模型重開後會自動繼續。

## UI 工作區

- **總覽**：使用 Run Center 的完整可用寬度顯示進度、目前動作、步驟、變更摘要與 Patch Review 入口。
- **Patch Review Workbench**：近全螢幕工作區，提供可拖曳並記住狀態的檔案清單、獨立捲動與分段渲染 Diff、Unified／Split、專注模式、Evidence 綁定 Approval 與 Partial Patch 重新驗證。
- **驗證**：Profile、Baseline、實際命令、Exit Code、耗時、Required／Blocks Apply、Build／Test／Lint／Type Check、外部驗證與相關 Evidence。
- **技術診斷**：可關閉、可最大化的完整高度工作區，容納 Agent 原始輸出、完整 Log、執行產物、修復策略、Event、Session／Process、Delivery／Rollback 證據與修復工具；不再重複正常 Patch Review。

Workflow 與 Chat 模式都保留執行模式、Options 與輸入框。步驟列的 `...` 會列出該步驟的 Prompt、Output、Feedback 與檔案；選擇後以大型 Markdown 彈窗開啟，可切換 Source／Preview、複製、下載或查看 Diagnostics。

Tabs 高度固定；大量 Log 會批次更新並限制瀏覽器渲染量，避免 UI 卡住。平台不會自動切走使用者目前查看的 Tab。

按 Stop 只會產生一個取消狀態，Cancelled Run 不會再開第二個重疊結果彈窗。

## Workflow 選擇

### General Auto Development

本機／小模型的預設選擇：

```text
AI 規劃 → 唯讀 Implementation Review → Task Loop → 產生測試
→ Focused Validation → 完整工程驗證 → Final Review
→ 不可變更外部驗證 → 確定性 Completion Gate
```

### Adaptive Auto Workflow

適合較強模型與自由任務。只有真正 Spec Conflict 才重新規劃；Test、Validation、Session、Context、未寫檔、Transport 與 Scope 問題都回到最小修復範圍。

### Security Vulnerability Scan

唯讀為主的盤點與安全檢查，不應生成產品程式碼。它會直接從 **Collect Security Manifest** 開始，刻意略過專案 Build／Test Baseline。

## 完成條件

模型說「完成」不代表交付，必須同時具備：

- Agent 真實建立的檔案變更；
- 無 Protected Path／Task Scope 違規；
- 相較 Baseline 沒有新增 Regression；
- Project Validation Profile Gate 通過；
- 必要且不可變更的 Validation Script 通過；
- Source Conflict 檢查與原子交付通過。

Controller 不會把 FILE Block 或 Tool-call JSON 轉成需求程式碼。

## V19 大型執行資訊檢視

總覽 Tab 以自己的主捲軸顯示執行步驟與目前步驟摘要。需要完整證據時，按 **放大檢視** 開啟大型 Step Dialog；Dialog 只有一個內容捲軸，可用關閉按鈕、背景或 Escape 關閉。

技術診斷中：

- 執行產物使用 Master–Detail Viewer；驗證與技術診斷可開啟全域 Artifact，Step 則使用保留 Step 上下文的獨立預覽 Dialog。兩者共用相同 Preview Renderer 與 Metadata 契約。
- 套用到專案位於並排／單欄 Patch 控制旁。
- Patch Review 的檔案清單與程式碼預覽各自捲動；Split 標題與內容共用精確 50/50 欄寬。工具／Controller Metadata 目錄不會進入 Patch，但專案內 `.qwen`、`.opencode` 仍會提供給 Agent cwd。Validation、Patch Review 與修復策略依各自工作區管理捲動。大型 Diff 與 Artifact 預覽採分段載入。
- Agent 輸出與 Logs 使用有上限的顯示視窗，長時間無人值守 Run 不會持續放大瀏覽器 DOM。
