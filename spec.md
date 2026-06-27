# Spec Summary - Qwen 可控 Workflow Web MVP

## Goal

建立一個像 ChatGPT 的 Web 平台，但底層是 **Python 控制 Qwen CLI 的可控 AI Workflow**。

核心原則：

```text
Qwen CLI = Agent Worker
Python Runner = Workflow Controller
Validator = Gate Keeper
Web UI = Operation Console
```

---

## Core Requirement

使用者在 Web UI 輸入需求後，系統必須由 Python Runner 依序呼叫 Qwen CLI 執行每個階段。

不可讓 Qwen 一次完成全部流程。

正確：

```text
Python → qwen spec
Python validate
Python → qwen review
Python gate
Python → qwen todo
Python validate
Python → qwen build
Python test
Python → qwen final-review
```

錯誤：

```text
qwen -p "請從需求做到完成"
```

---

## Workflow

```text
Requirement
→ Qwen Generate Spec
→ Python Validate Spec
→ Qwen Review Spec
→ Python Spec Gate
→ Qwen Generate Todo
→ Python Validate Todo
→ Qwen Review Todo
→ Python Todo Gate
→ Qwen Build
→ Python Run Test
→ Qwen Final Review
→ Python Final Gate
→ Done / Failed
```

---

## MVP Scope

- Web UI 類似 ChatGPT
- Session 分區
- User 可輸入 Requirement
- 每個 Session / Run 有獨立 Workspace
- Backend 使用 Python / FastAPI
- Python 使用 subprocess 呼叫 Qwen CLI
- 每一步固定 Prompt
- 每一步固定 Output File
- Spec / Todo 用 Python Validator 檢查
- Review / Build / Final Review 都基於呼叫 Qwen
- Test 由 Python subprocess 執行
- Web UI 顯示 Workflow 狀態、Log、Artifacts
- 任何 Gate 失敗就停止流程

---

## Out of Scope

- 登入權限
- 多人 RBAC
- Queue / Celery / Redis
- Vector DB / Project Index
- MCP 整合
- Git PR 自動化
- 多 Agent 並行 Review
- Production Deployment

---

## Architecture

```text
Browser
  ↓
Web UI
  ↓
FastAPI Backend
  ↓
Python Workflow Runner
  ↓
Qwen CLI
  ↓
Workspace / Source Code / Output Files
```

---

## Main Components

### 1. Web UI

負責：

```text
Session List
Chat-like Input
Workflow Status
Step Logs
Artifact Viewer
Reset Session
```

---

### 2. Python Backend

負責：

```text
Session 管理
Message 儲存
Workflow Run 建立
Workspace 建立
API 提供
SSE / WebSocket Log Streaming
```

---

### 3. Workflow Runner

負責：

```text
控制步驟順序
呼叫 Qwen CLI
執行 Validator
執行 Test Command
更新 State
寫入 Log
判斷 PASS / FAIL
失敗停止流程
```

---

### 4. Qwen CLI Client

Python 必須封裝 Qwen 呼叫：

```python
class QwenCliClient:
    def run(self, prompt: str, cwd: Path, timeout_sec: int = 1200) -> str:
        ...
```

實作方式：

```python
subprocess.run(
    ["qwen", "-p", prompt],
    cwd=str(cwd),
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=timeout_sec
)
```

---

## Workspace Structure

每個 Run 必須獨立：

```text
workspaces/
  session-{session_id}/
    run-{run_id}/
      requirement.md
      output/
        spec.md
        spec-review.md
        todo.md
        todo-review.md
        build-result.md
        test-result.md
        final-review.md
      .workflow/
        state.json
        run-log.md
```

---

## Required Workflow Steps

### 1. Generate Spec

呼叫 Qwen。

Input：

```text
requirement.md
prompts/01_spec.md
```

Output：

```text
output/spec.md
```

限制：

```text
只能產生 spec.md
不得產生 todo
不得修改程式碼
```

---

### 2. Validate Spec

Python 執行。

檢查：

```text
spec.md 存在
包含 Goal / Scope / Out of Scope / Input / Output / Rules / Acceptance Criteria / Unknowns
至少一個 AC-001
AC ID 不可重複
```

Fail 立即停止。

---

### 3. Review Spec

呼叫 Qwen。

Output：

```text
output/spec-review.md
```

必須包含：

```text
Status: PASS
```

否則停止。

---

### 4. Generate Todo

呼叫 Qwen。

Input：

```text
spec.md
requirement.md
```

Output：

```text
output/todo.md
```

限制：

```text
只能根據 spec.md 產生 todo.md
不得修改程式碼
不得擴充 spec 沒有的需求
```

---

### 5. Validate Todo

Python 執行。

檢查：

```text
todo.md 存在
包含 Todo List / Test Plan / Done Criteria
每個 AC 都出現在 todo.md
至少一個 TODO-001
至少一個 TEST-001
```

Fail 立即停止。

---

### 6. Review Todo

呼叫 Qwen。

Output：

```text
output/todo-review.md
```

必須包含：

```text
Status: PASS
```

否則停止。

---

### 7. Build

呼叫 Qwen。

Input：

```text
spec.md
todo.md
source code
```

Output：

```text
output/build-result.md
```

限制：

```text
只能做 todo.md 內任務
不得修改 spec.md / todo.md
不得重構無關程式碼
不得刪除測試
資訊不足要輸出 BLOCKED
```

必須包含：

```text
Status: DONE
```

否則停止。

---

### 8. Run Test

Python 執行。

```text
使用 configurable test command
寫入 output/test-result.md
ExitCode = 0 才 PASS
```

Fail 立即停止。

---

### 9. Final Review

呼叫 Qwen。

Input：

```text
spec.md
todo.md
test-result.md
```

Output：

```text
output/final-review.md
```

必須包含：

```text
Status: PASS
```

否則 Workflow Failed。

---

## Validator Rules

Python Validator 必須處理：

```text
檔案是否存在
必要 section 是否存在
AC / TODO / TEST ID 是否存在
AC 是否都有 Todo
AC 是否都有 Test
Review 是否 Status: PASS
Build 是否 Status: DONE
Test ExitCode 是否為 0
```

---

## API MVP

```text
POST /api/sessions
GET  /api/sessions
POST /api/sessions/{session_id}/messages
POST /api/sessions/{session_id}/workflow-runs
GET  /api/workflow-runs/{run_id}
GET  /api/workflow-runs/{run_id}/steps
GET  /api/workflow-runs/{run_id}/artifacts
GET  /api/artifacts/{artifact_id}
GET  /api/workflow-runs/{run_id}/events
```

---

## UI MVP

```text
左側：Session List
中間：Chat-like Messages + Input
右側：Workflow Steps + Logs + Artifacts
```

Artifact 可查看：

```text
requirement.md
spec.md
spec-review.md
todo.md
todo-review.md
build-result.md
test-result.md
final-review.md
run-log.md
state.json
```

---

## Acceptance Criteria

- AC-001：User 可以建立 Session
- AC-002：User 可以輸入 Requirement
- AC-003：系統會建立獨立 Workspace
- AC-004：Python 會呼叫 Qwen 產生 spec.md
- AC-005：Python 會 validate spec.md
- AC-006：Spec review 必須由 Qwen 執行
- AC-007：Spec review 不是 PASS 時流程停止
- AC-008：Python 會呼叫 Qwen 產生 todo.md
- AC-009：Python 會 validate todo.md
- AC-010：Todo review 必須由 Qwen 執行
- AC-011：Todo review 不是 PASS 時流程停止
- AC-012：Build 必須由 Qwen 執行
- AC-013：Build 不是 DONE 時流程停止
- AC-014：Test 必須由 Python 執行
- AC-015：Test failed 時流程停止
- AC-016：Final Review 必須由 Qwen 執行
- AC-017：Final Review 不是 PASS 時 workflow failed
- AC-018：Web UI 可顯示 step status
- AC-019：Web UI 可顯示 logs
- AC-020：Web UI 可查看 artifacts

---

## Done Definition

完成後應可做到：

```text
開啟 Web UI
建立 Session
輸入 Requirement
Python Runner 建立 Workflow Run
每一步都透過 qwen CLI 或 Python Validator/Test 執行
每一步都有狀態
每一步都有輸出檔
失敗會停止
成功才進下一步
Web UI 可查看 logs 與 artifacts
```

---

## Final Principle

```text
所有 AI 任務都基於呼叫 Qwen CLI。
但 Qwen 不能控制流程。
流程控制、驗證、Gate、Test、State 必須由 Python 負責。
```
