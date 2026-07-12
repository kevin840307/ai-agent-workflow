# 系統架構

## 責任分工

```text
Qwen／OpenCode
  理解、規劃、以有效 Project Path cwd 編輯、修復、Review

Workflow Kernel
  確定性狀態、Task Contract、Retry／Recovery、Session、Checkpoint、
  Validation、原子交付、Evidence

FastAPI／Web UI／CLI
  Project／Run 操作、Simple／Advanced 顯示、診斷與 Asset
```

Controller 不實作使用者要求的產品功能。它可以檢查、Snapshot、比較、驗證、於原子交付時複製已驗證的 Agent 輸出並回滾，但不會自行生成需求程式碼。

## 正式 Runtime 邊界

- `app/workflow_engine/`：狀態機與 Executor Contract。
- `app/workflow_runtime/`：Agent Action、Validation、Retry、Context、Checkpoint、Autopilot State、Preflight、Environment Health、Profile、Atomic Delivery 與 Evidence。
- `app/services/`：Use Case API 與 Recovery 協調。
- `app/workflow/agents/providers/`：Qwen、OpenCode、Generic CLI Adapter。
- `app/persistence/`：SQLite WAL 與正規化投影。

`app/runtime_modules/` 只保留隔離的低階相容工具，新 Orchestration 不得放入。

## Autopilot 狀態機

無人值守 Run 會保存與 UI 文案無關的精簡狀態：

```text
discovering → executing → finalizing → verified → completed
```

Preflight 解析 Environment Health、可重用 Project Validation Profile 與 Baseline。重要轉換都持久化，Controller 重啟後才能判斷是否可安全恢復。

## Project 與 Session 隔離

- 一般 Agent 以使用者選擇的 Project Path 作 cwd。
- 隔離無人值守 Run 使用保留專案 CLI 設定的有效 Project Path 副本。
- 同一原始專案只允許一個 Writer。
- 不同專案／Session 可透過 Provider Semaphore 並行。
- Planning、Implementation、Validation、Review 可使用角色 Session。
- Context 過高或重複失敗時，用精簡 Handoff 切換 Fresh Session。

## Baseline 與 Validation Profile

Profile 依 resolved Project Path 建立 Key，保存於 Controller 資料目錄。Descriptor Fingerprint 追蹤 Build／Test／Validation 描述檔。所有 Profile Command 都從有效 Project Path 執行，不把語言專用命令寫死在 Workflow。

Baseline 會區分專案原本就存在的錯誤與本次新增 Regression。完成條件阻擋新增或惡化的失敗，不要求 Agent 修復無關且完全不變的歷史錯誤。

## 依進展判斷 Recovery

Recovery 同時使用 Failure Identity 與 Progress Identity。Progress Signature 包含 Filesystem、Changed Files、Task、Validation Evidence 與 Checkpoint。有改善時可以繼續；錯誤與進展都完全相同時會換策略／Session，最後才由累積 Budget 停止。

## 原子交付

隔離無人值守 Run：

```text
Snapshot 原專案 → Agent 修改隔離有效 Project Path → 驗證
→ 檢查原專案外部衝突 → 原子複製已驗證的 Agent 變更
→ 套用後 Fast Validation → 保留或回滾
```

Atomic Delivery 只複製 Agent 產生的 Bytes，不會生成內容。原專案被外部修改或套用後驗證退化時，會拒絕或回滾。

## 連線與 Durable Recovery

Provider Connectivity 與 Workflow Event Stream 分開探測。無人值守的暫時連線失敗會低頻等候，不快速消耗 Retry。EventSource 自動重連並重新同步 Run 狀態。

Controller 啟動時會自動恢復具有安全持久化資訊的 Interrupted Unattended Run。Checkpoint 與 Project Lock 避免重複 Writer。

## Evidence 與儲存

SQLite 使用 WAL，並以 Runs、Steps、Tasks、Sessions、Events、Validation、File Changes、Checkpoints、Locks 等投影查詢。相容 Document Snapshot 只保留給 Atomic Recovery。敏感資訊在持久化／顯示前遮罩。

## 前端 Layout 邊界

Simple／Advanced 共用同一 State Tree。Run Center 只負責可閱讀的總覽與驗證；總覽開啟唯一一套近全螢幕 Patch Review Workbench，正常核准／套用流程不再重複放在技術診斷。技術診斷保留 Agent、Log、修復證據、Session／Process、Delivery／Rollback 與共用執行產物 Viewer。每個工作區自行管理捲動，不允許多層固定高度互相壓縮。

## 前端模組邊界

```text
static/js/pages/
├── workflow-designer.js             # 精簡頁面入口
├── workflow-designer/
│   ├── controller.js
│   ├── asset-tools.js
│   ├── layout-renderer.js
│   ├── step-settings-renderer.js
│   ├── template-editor.js
│   ├── import-export.js
│   ├── function-catalog.js
│   ├── model.js
│   └── utils.js
├── ai-workflow-assets.js
└── ai-workflow-assets/
    └── asset-manager.js
```

頁面入口保持精簡，State、Render、Asset Edit 與 Interaction 放在聚焦模組，避免 UI 修正再次堆成單一大型 Script。
