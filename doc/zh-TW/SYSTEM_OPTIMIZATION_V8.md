# System Optimization V8

V8 將 Agent Workflow Web 從「以 Raw Log 與大量 Artifact 為中心的開發工具」重整為「可恢復、可驗證、可理解、可控制的本機 Workflow 產品」。本版本保留 V7 已驗證的 Project Path、filesystem-first、phase ownership 與 deterministic repair，並將原本分散的能力整併成統一的執行核心與 Run Center。

## 1. 產品目標

一般使用者只需要：

1. 選擇 Project Path。
2. 輸入需求。
3. 接受或忽略系統建議。
4. 開始執行。
5. 在「總覽／變更／驗證」確認結果。

Prompt、Session ID、Console、Artifact Index、Patch JSON、Repair Policy 與 Debug 資料不再佔據主要操作畫面；它們集中在延遲載入的「技術診斷」抽屜。

## 2. 現有架構盤點後的整併方式

V8 沒有推倒重寫既有功能，而是把既有模組整理為七個責任區：

| 責任區 | 主要模組 | 功能 |
|---|---|---|
| Workflow Planner | workflow assets、General／Adaptive planner | 產生 Task、AC、驗證需求與複雜度 |
| State Machine／Orchestrator | `workflow_engine/state_machine.py`、executor | 原子化狀態轉移、Step 執行、Checkpoint、Retry |
| Workspace Manager | run diff、snapshot、test layout、phase ownership | Project Path、diff、精準 rollback、candidate 保留 |
| Session Manager | `services/agent_session_manager.py` | Planning／Build／Validation／Review Session 分流與恢復 |
| Policy Engine | project guard、phase ownership、read-only review | 限制可寫路徑、危險操作與 Step 檔案 ownership |
| Validation Engine | workflow functions、pytest、validation.py、hygiene | deterministic validation first，AI Review second |
| Evidence Store | SQLite v2 projection、artifact policy | 結構化保存 Run、Task、Event、Validation、Diff、Checkpoint |

General 與 Adaptive 保留不同規劃策略，但共用 Agent runtime、Workspace、Retry、Validation、Session 與 Evidence 核心。

## 3. 正式狀態機與 Checkpoint

Run 狀態：

```text
QUEUED → RUNNING → WAITING_INPUT / CANCELLING → DONE / FAILED / CANCELLED
```

每次狀態轉換都保留：

- from / to
- reason
- timestamp
- current phase
- last checkpoint

每個成功 Step 會建立結構化 Checkpoint。服務重啟後，Active Run 會被標記為 `INTERRUPTED`、釋放 Project Lock，並提供「從最近 Checkpoint 繼續」。

## 4. Session Manager 與 Context Recovery

Session 依角色分流：

- Planning：fresh、read-only
- Build：同一 Task 可 resume
- Validation repair：依錯誤策略使用 resume 或 fresh
- Review：永遠 fresh、read-only

恢復規則：

| 情境 | 策略 |
|---|---|
| Session 已存在 | Resume |
| Session 不存在 | Create |
| Timeout | 保留有效檔案，下一次 Fresh Session |
| Rollback | Fresh Session，避免模型記憶與檔案不一致 |
| Context compression failed | 建立 handoff 摘要並 Fresh Session |
| Review | 不繼承 Build 對話 |

## 5. Workspace、Policy 與 Project Lock

正常 `auto_apply` 模式：

```text
Agent cwd/write root = 使用者選擇的 Project Path
.ai-workflow          = Controller state、log、prompt、evidence
```

同一 Project 同時間只允許一個 Write Run。終止、取消、服務重啟與 stale-owner recovery 都會同時清理：

- 磁碟 lock file
- Run State 的 `project_lock`
- SQLite `project_locks` projection

Planner／Review 為 read-only。Build／Generate Tests 採 phase ownership：合法檔案保留，越權檔案精準還原，不會因單一錯誤 rollback 整個 Project。

## 6. Validation Engine

固定順序：

```text
Path／Permission Gate
→ Syntax／Compile Gate
→ Test Layout Preflight
→ Unit Test
→ User Validation Script
→ Project Hygiene
→ Acceptance Evidence
→ Read-only AI Review
→ Final Gate
```

Python Gate 優先序：

```text
validation.py → pytest → run_tests.py → VALIDATION_NOT_EXECUTED
```

若有 Python source 卻沒有可執行驗證，不再假裝 PASS。

`test_*.py` 與 `tests/` 衝突、空 root test、pytest cache 等可由 Controller 確定性處理，不消耗 AI Retry。

## 7. Typed Error 與 Recovery Budget

固定 Error Code 包含：

- `SESSION_NOT_FOUND`
- `SESSION_ALREADY_EXISTS`
- `CONTEXT_LIMIT_REACHED`
- `TIMEOUT`
- `NO_FILE_CHANGE`
- `PATH_POLICY_VIOLATION`
- `TEST_LAYOUT_CONFLICT`
- `TEST_FAILED`
- `VALIDATION_NOT_EXECUTED`
- `INVALID_OUTPUT`
- `REVIEW_MUTATED_PROJECT`
- `DUPLICATE_IMPLEMENTATION`
- `INTERRUPTED`

Retry 不只是一個 `x/99` 數字。Run 會分開記錄：

- agent attempts
- deterministic／automatic repairs
- session restarts
- replans
- manual actions
- consecutive failures

成功 Step 只重置 consecutive failure streak，累積資料仍供報表與分析使用。

## 8. SQLite v2 Evidence Store

SQLite 使用 WAL、busy timeout、foreign keys、schema migration 與 backup。保留舊 JSON state 相容性，同時建立正規化 projection：

```text
runs
run_steps
tasks
agent_sessions
run_events
run_artifacts
validation_results
file_changes
checkpoints
project_locks
```

Final Report、Run Center 與 Analytics 直接使用結構化 Evidence，不再重新解析 Raw Log。

## 9. Artifact Compact-first

預設 `AIWF_ARTIFACT_MODE=compact`：

- 不為每個 Step 複製一份 JSON。
- 不鏡像 Console、State、Events、Trace 到多個目錄。
- 一般 UI 只顯示 Final Report、Diff、Test、Validation 與 Gate。
- Terminal Run 可將 Prompt、Log、State、Trace 打包為單一 `diagnostics.zip`。
- `AIWF_PRUNE_DIAGNOSTIC_FILES=1` 時可刪除冗餘 mirror folders。

Artifact Index 仍存在供 API、replay 與維護使用，但不再是一般使用者的主要功能。

## 10. Run Center UI／UX

主要區域只保留：

### 總覽

- Current Action
- 為什麼正在做這件事
- 下一步
- Progress
- 使用者友善 Step 名稱
- Completion Summary
- 建議操作

### 變更

- Added / Modified / Removed
- 檔案來源 Step
- Diff
- 自動清理紀錄

### 驗證

- Syntax／Compile
- Unit Tests
- Validation Script
- Project Hygiene
- AI Review
- Final Gate

狀態顏色區分 PASS、RUNNING、WARNING、FAILED、SKIPPED 與 NOT CONFIGURED。

### 技術診斷抽屜

只有使用者主動開啟才載入：

- 執行時間線與 Console
- Agent output / log
- 全部 Artifacts
- Patch 審核／套用到專案
- Repair Policy
- 系統健康／Analytics／SQLite Projection
- 精簡 Debug JSON

原本分散的 Console、Diff、Patch、Artifact Index、Copy Debug Bundle、Repair Policy 不再各自佔據 Detail tabs。

## 11. Setup Wizard

Setup Status 提供七項 readiness：

1. SQLite 與資料目錄
2. Project Path 寫入
3. Agent CLI
4. 模型連線與設定
5. Context Window
6. Session Resume／Fresh Recovery
7. Tool Calling 與寫檔能力

阻擋項目與建議項目分開呈現。警告不一定阻擋短任務，但會提示長時間 Workflow 的風險。

## 12. Complexity Router 與智慧建議

使用者輸入需求後，系統依需求、Project、歷史 Run 與 Agent readiness 建議：

- Workflow
- Agent
- Small／Normal／Strong Profile
- Thinking Level
- Task 數範圍
- 執行時間範圍
- Local compute cost
- Prompt budget
- 歷史成功模板
- 常見錯誤 Repair Strategy

建議只會顯示「套用建議」按鈕，不會自動改掉使用者選擇。

Complexity Profile：

| Profile | 建議流程 |
|---|---|
| Tiny | Execute → Test → Complete |
| Standard | Plan → Task Loop → Validate → Review |
| Complex | Architecture → Task Loop → Assembly → Multi-gate Review |

## 13. Workflow Designer

保留並強化三層操作：

- Simple：視覺化 Step 卡片
- Advanced：Agent、Timeout、Retry、Validation、Permission、Failure Target
- JSON：完整 Workflow Schema

支援版本、Import／Export、Schema Validation、System Workflow protection 與 API-backed storage。

## 14. Analytics 與可觀測性

`/api/analytics/summary` 提供：

- Workflow 成功率
- 平均 Retry
- 平均執行時間
- 常見 Error Code
- 最慢 Step
- 可自動修復比例
- Workflow 比較

`/api/optimization/recommend` 使用這些資料做執行前建議。技術診斷的「系統健康」集中顯示 Setup、Analytics 與 SQLite Projection。

## 15. API 摘要

| API | 用途 |
|---|---|
| `GET /api/setup/status` | 七項環境 readiness |
| `POST /api/setup/smoke` | 隔離模型／Session／Tool Calling smoke test |
| `POST /api/optimization/recommend` | 執行前智慧建議 |
| `GET /api/analytics/summary` | Workflow 指標 |
| `GET /api/workflow-runs/{id}/overview` | Run Center 資料 |
| `POST /api/workflow-runs/{id}/actions` | retry/resume/stop/keep changes |
| `GET /api/workflow-runs/{id}/diagnostics` | 技術診斷 |
| `POST /api/workflow-runs/{id}/artifacts/compact` | 診斷壓縮 |
| `GET /api/maintenance/store/status` | SQLite projection 狀態 |
| `POST /api/maintenance/store/backup` | SQLite backup |

## 16. 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `AIWF_ARTIFACT_MODE` | `compact` | `compact` 或 `full` |
| `AIWF_PRUNE_DIAGNOSTIC_FILES` | `0` | 壓縮後刪除冗餘 mirror |
| `AIWF_DEFAULT_PATCH_MODE` | `auto_apply` | 正常寫入 Project Path |
| `AIWF_CONTEXT_WINDOW` | 未指定 | 覆寫模型 context window |
| `QWEN_MOCK` | `0` | deterministic test agent |
| `QWEN_TIMEOUT_SEC` | 依設定 | Agent timeout |

## 17. 測試策略

V8 測試涵蓋：

- State transition
- Session role/fresh policy
- SQLite projection、migration、backup
- Project Lock lifecycle
- Restart recovery
- Artifact compact-first
- Typed errors
- Run Center／Diagnostics UI contracts
- Setup readiness
- Optimization recommendation
- General／Adaptive E2E
- Workflow assets、validation、retry、safety、path guard
- Browser static smoke

由於部分 FastAPI TestClient／長時間 Workflow fixture 會在同一 pytest process 共享背景 task，完整矩陣採隔離 process 分組執行。真實 Qwen CLI、Playwright 與 clean-repository smoke 仍是 opt-in 測試。

## 18. 使用方式

更新程式後：

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

第一次使用先開啟「環境檢查」。建立新的 Run 才會套用 V8 State、Session、Artifact、UI 與 Recovery 行為；舊 Run 保留原始記錄，不會被重寫。
