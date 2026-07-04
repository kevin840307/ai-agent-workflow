# TODO - Single Machine Stability

本 TODO 針對目前平台定位：

```text
單機使用
允許多個 request
不導入 DB / Redis / Celery
不支援多 worker / 多 instance
目標是讓 Chat 與 Workflow 在單機多 request 下穩定、不重複、不互相污染
```

---

## Goal

讓系統從「MVP 可用」提升到「單機穩定可用」。

核心原則：

```text
1. 所有關鍵寫入要 atomic
2. 所有共享狀態要有 lock
3. 同一個 Chat Session 不允許同時產生多個 assistant response
4. 同一個 Project 不允許同時跑多個 Workflow Run
5. Workflow / Chat 狀態不能只靠前端記憶
6. uvicorn 固定 workers=1
```

---

# P0 - 必做，避免單機多 request 造成資料錯亂

## 1. 固定單 process 執行

### Problem

目前使用 `store.json` 與 `asyncio.Lock`，只能保護同一個 Python process。

如果使用：

```bash
uvicorn app.main:app --workers 4
```

會有多個 process 同時寫入 `store.json` 的風險。

### TODO

- [ ] 明確文件化：目前只支援 `workers=1`
- [ ] 啟動時偵測或警告不支援多 worker
- [ ] README / TESTING / run script 補上建議啟動方式

### Suggested Command

```bash
python -m uvicorn app.main:app --reload --port 8000
```

正式單機也建議：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 2. Store 寫入改成 Atomic Write

### Problem

目前如果直接寫：

```python
store_path.write_text(...)
```

當 process crash 或兩個 request 寫入交錯時，可能造成：

```text
store.json 半寫入
store.json 損毀
資料被覆蓋
```

### TODO

- [ ] 所有 `store.json` 寫入集中在 Store layer
- [ ] 寫入時使用全域 `asyncio.Lock`
- [ ] 先寫入 `store.json.tmp`
- [ ] flush / fsync
- [ ] 使用 `os.replace(tmp, store.json)` 原子替換
- [ ] 寫入失敗時保留舊的 `store.json`

### Target Behavior

```text
多個 request 同時寫 store，也只能一個一個寫
寫到一半 crash，不會破壞原 store.json
```

---

## 3. Chat Session Lock

### Problem

同一個 chat session 可能發生：

```text
使用者連點送出
前端重送 request
上一個 assistant 還在產生，下一個 message 又送出
```

會導致：

```text
同一 session 多個 assistant response 同時產生
message 順序混亂
上下文不一致
```

### TODO

- [ ] 新增 `CHAT_SESSION_LOCKS: dict[str, asyncio.Lock]`
- [ ] 同一個 `session_id` 同時間只允許一個 assistant response
- [ ] 如果 session busy，回傳 409
- [ ] 前端顯示「目前回覆產生中」
- [ ] assistant 完成 / 失敗後釋放 lock

### Suggested Rule

```text
同一個 chat session：不可並行
不同 chat session：可以並行
```

---

## 4. Chat Request Idempotency

### Problem

使用者連點、網路 retry、前端 timeout 重送，可能造成同一句 message 被處理多次。

### TODO

- [ ] 前端送 chat message 時產生 `clientRequestId`
- [ ] 後端儲存 `session_id + client_request_id`
- [ ] 同一組 key 只處理一次
- [ ] 如果重複 request，回傳已存在的 message / response 狀態
- [ ] 避免重複呼叫 Qwen / OpenCode

### Suggested Request

```json
{
  "message": "幫我分析這個錯誤",
  "clientRequestId": "uuid-from-browser"
}
```

---

## 5. Chat Message 狀態化

### Problem

目前如果 assistant 回覆到一半失敗，可能只看到 HTTP error，reload 後不知道剛剛發生什麼。

### TODO

- [ ] assistant message 建立時先存成 `pending`
- [ ] 開始產生時改成 `running`
- [ ] 成功後改成 `completed`
- [ ] 失敗後改成 `failed`，保留 error message
- [ ] 前端支援顯示 failed assistant message
- [ ] 前端支援 retry / regenerate

### Suggested Status

```text
pending
running
completed
failed
cancelled
```

---

## 6. Workflow Project Lock

### Problem

同一個 project 同時跑兩個 workflow，可能造成：

```text
artifact 覆蓋
run workspace 混亂
project files 同時被修改
step 狀態互相影響
```

### TODO

- [ ] 新增 `PROJECT_RUN_LOCKS: dict[str, asyncio.Lock]`
- [ ] 建立 run 前檢查同 project 是否已有 active run
- [ ] active status 包含：
  - queued
  - running
  - waiting_input
  - cancelling
- [ ] 同 project active run 存在時，回傳 409
- [ ] cancel / failed / completed 後釋放 lock

### Suggested Rule

```text
同一個 project：同時間只允許一個 workflow run
不同 project：可以並行
```

---

## 7. Workflow Run Task Registry

### Problem

目前 workflow 若使用 background task，需要知道：

```text
哪些 run 正在執行
是否可以 cancel
server reload 後哪些 run 被中斷
```

### TODO

- [ ] 維護 `RUNNING_TASKS: dict[str, asyncio.Task]`
- [ ] 建立 run 後註冊 task
- [ ] run 完成 / 失敗 / cancel 後移除 task
- [ ] cancel API 能找到 task 並 cancel
- [ ] timeout 能正確標記 step / run failed
- [ ] server startup 執行 `mark_interrupted_runs()`

### Target Behavior

```text
前端按 Cancel 後，後端真的停止該 run
server restart 後，舊 running run 會標記 interrupted / failed
```

---

## 8. Artifact Atomic Write

### Problem

Workflow function 或 AI step 寫 artifact 時，如果寫到一半失敗，可能留下半個檔案。

### TODO

- [ ] 所有 artifact 寫入改用 helper
- [ ] helper 寫入流程：
  - 寫 `filename.tmp`
  - flush / fsync
  - `os.replace(tmp, filename)`
- [ ] 禁止直接 `path.write_text(...)`
- [ ] Python workflow function guide 補充 atomic write 規則

### Target Behavior

```text
artifact 要嘛是舊版完整檔案
要嘛是新版完整檔案
不會出現半個檔案
```

---

# P1 - 建議做，提升可恢復性與 UI 穩定

## 9. Durable Workflow Timeline

### Problem

SSE event 是 memory-only，reload 後即時事件會消失。

### TODO

- [ ] run 內保存 timeline / events
- [ ] 每個重要事件都寫入 run state
- [ ] 前端 reload 後可透過 API 還原 timeline
- [ ] SSE 只負責即時更新，不當唯一狀態來源

### Suggested Event

```json
{
  "ts": "2026-06-29T15:00:00Z",
  "runId": "run_xxx",
  "stepKey": "validate_spec",
  "type": "step_failed",
  "message": "spec.md missing Goal section"
}
```

---

## 10. 統一 API Error Format

### Problem

目前不同 API 可能回傳不同錯誤格式，前端處理會分散。

### TODO

- [ ] 定義統一錯誤格式
- [ ] 常見錯誤加 code
- [ ] 前端統一使用 `showApiError()`
- [ ] 409 / 400 / 404 / 500 都保持一致 payload

### Suggested Error Format

```json
{
  "ok": false,
  "error": {
    "code": "WORKFLOW_ALREADY_RUNNING",
    "message": "This project already has an active workflow run.",
    "details": {
      "projectId": "xxx",
      "runId": "yyy"
    }
  }
}
```

---

## 11. Static Version 集中管理

### Problem

目前 cache version 如果散落在多個 HTML / CSS import，容易發生：

```text
HTML 新版
JS 舊版
CSS 舊版
```

導致奇怪前端錯誤。

### TODO

- [ ] 將 static version 集中到單一常數
- [ ] HTML template 使用同一個 version
- [ ] CSS `@import` 也使用同一版本或改成不用 query string
- [ ] 修改 static 後只需要改一個地方

### Suggested

```python
STATIC_VERSION = "20260629-static-modules"
```

---

## 12. Sidebar / Layout 共用 Component

### Problem

`index.html` 與 `workflow-designer.html` 目前各自維護 sidebar，容易造成：

```text
寬度不一致
Runner / Workflows 位置不同
collapse 行為不同
active 樣式不同
```

### TODO

- [ ] 抽出 `static/css/sidebar.css`
- [ ] 抽出 `static/js/components/sidebar.js`
- [ ] index / workflow-designer 共用同一套 nav item render
- [ ] collapse state 使用同一個 localStorage key
- [ ] Runner / Workflows icon、size、padding、active 樣式一致

---

## 13. Frontend Render Flow 收斂

### Problem

如果每個 event handler 直接改 DOM，容易出現：

```text
state 已改，但 UI 沒更新
切 Step Type 後欄位不刷新
modal / sidebar 不同步
```

### TODO

- [ ] event handler 只負責更新 state
- [ ] 所有 UI 更新集中呼叫 render function
- [ ] workflow-designer 定義清楚：
  - `renderSidebar()`
  - `renderWorkflowHeader()`
  - `renderStepList()`
  - `renderStepSettings()`
  - `renderArtifacts()`
- [ ] 新增 smoke test 檢查 step type / function 切換後 UI capability 正確

---

# P2 - 單機長期使用再做

## 14. Artifact Cleanup

### TODO

- [ ] 設定保留最近 N 個 run
- [ ] 設定保留最近 N 天 artifact
- [ ] 提供手動 cleanup API
- [ ] cleanup 前確認 run 不在 active 狀態

---

## 15. Log Rotation

### TODO

- [ ] workflow events / app logs 支援 rotation
- [ ] 避免長期使用後 log 無限成長
- [ ] 保留錯誤 run 的完整 logs

---

## 16. Health Check

### TODO

- [ ] 新增 `/health`
- [ ] 新增 `/ready`
- [ ] 檢查：
  - store path readable
  - store path writable
  - runs directory writable
  - static files available

---

## 17. Basic Metrics

### TODO

- [ ] 記錄 workflow run duration
- [ ] 記錄 step duration
- [ ] 記錄 failed count
- [ ] 記錄 active run count
- [ ] 記錄 chat failed count
- [ ] 前端或 log 顯示基本統計

---

# Not Now - 目前不建議做

在「單機使用，多 request」條件下，以下先不要做，避免過度設計：

```text
Postgres
Redis
Celery
多 worker
多 instance
distributed lock
user permission system
durable SSE replay
完整 observability stack
```

未來如果要多人正式使用，再升級。

---

# Implementation Order

建議照這個順序做：

```text
1. Store atomic write
2. Artifact atomic write
3. Chat session lock
4. Chat client_request_id
5. Chat message status
6. Workflow project lock
7. Workflow task registry / cancel / timeout cleanup
8. Durable workflow timeline
9. Static version 集中
10. Shared sidebar component
```

---

# Definition of Done

完成後應該能保證：

```text
1. 單機多 request 不會寫壞 store.json
2. 同一個 chat session 不會同時產生兩個 assistant response
3. 重複送出同一個 chat request 不會產生兩筆 message
4. 同一個 project 不會同時跑兩個 workflow
5. workflow cancel 會真的停止 task
6. server restart 後 running run 會被標記 interrupted / failed
7. artifact 不會出現半寫入檔案
8. reload 頁面後仍能看到 run 目前狀態與歷史事件
9. index / workflow-designer sidebar 行為一致
10. 修改 static 後不需要到處改 cache version
```
