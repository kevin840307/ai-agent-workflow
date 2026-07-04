# Qwen Workflow Web

這是一個 **AI Agent Workflow Runner**。目標不是只做一般聊天，而是讓使用者在 Web UI 輸入需求後，由 Python Runner 控制固定流程，並呼叫 Qwen / OpenCode 等 Agent 逐步產出、驗證、失敗重試與修復。

核心概念：

- **Agent 負責產出**：例如產生 spec、todo、程式碼、測試、文件。
- **Python Runner 負責控制**：流程順序、retry、validation、狀態、log、artifact。
- **Workflow Asset 可編輯**：workflow、step prompt、contract、python function 分離管理。
- **Project 隔離**：每個專案有自己的 session / workspace / output artifacts。

## 主要功能

| 功能 | 說明 |
|---|---|
| Chat UI | 類 ChatGPT 的專案對話介面 |
| Workflow Runner | 選擇 workflow 後，依照步驟自動執行 |
| Workflow Designer | 編輯 workflow step、prompt、retry、review、validation 設定 |
| AI Workflow Assets | CRUD 管理 prompt / contract / Python function |
| Qwen / OpenCode Provider | 可使用 Qwen CLI 或 OpenCode CLI 作為 Agent Worker |
| Retry / Repair Loop | Step 失敗時可把錯誤訊息回灌到指定 step 修復 |
| External Validation | 可輸入 Python validation script；未輸入則跳過並視為 PASS |
| Artifacts | 每次 run 會保留 output 檔案、log、結果報告 |

## 目前內建 Workflow

### Adaptive Auto Workflow

簡化版全自動開發流程：

```text
User Requirement
  -> Step 1: Auto Generation
  -> Step 2: AI Review
  -> Step 3: Run External Validation optional
```

第三步使用共用的 `run_external_validation` Python Function：

- 沒有輸入 Validation Script：直接產生 PASS，代表跳過外部驗證。
- 有輸入 Python Script：執行該 script。
- Script 失敗：把 stdout / stderr / exit code 寫入 artifact，並回到 `auto_generation` 修復。

### General Auto Development

較完整的工程流程，適合需要 Spec / Todo / Build / Test / Review / Validation / Final Gate 的任務。

## 快速啟動

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

開啟：

```text
http://127.0.0.1:8000
```

建議單機 MVP 使用單一 process，不要開多個 uvicorn worker。此專案目前的 run lock、chat lock、cancel lock 都是以本機單程序為主。

## 基本使用方式

1. 在 UI 建立或選擇 Project。
2. 設定 Project Path。
3. 選擇 Workflow，例如 `Adaptive Auto Workflow`。
4. 在輸入框寫需求。
5. 需要外部驗證時，填入 Validation Script，例如：

```text
tools/validate_config.py
```

6. 按下 Run，系統會依 workflow 自動執行並產生 artifacts。

Validation Script 可選擇支援下列參數：

```text
--project <project_path> --workspace <run_workspace> --output <output_dir>
```

如果 script 不支援這些參數，runner 會自動改用：

```text
python <script>
```

## Agent 設定

常用環境變數：

| 變數 | 說明 |
|---|---|
| `QWEN_BIN` | Qwen CLI 路徑，Windows 預設 `qwen.cmd` |
| `QWEN_USE_SERVE` | 設為 `1` 時使用 qwen serve API，預設走 CLI |
| `QWEN_TIMEOUT_SEC` | Qwen timeout 秒數，預設 1200 |
| `QWEN_MOCK` | 設為 `1` 可用 mock agent 做本機測試 |
| `OPENCODE_BIN` | OpenCode CLI 路徑，Windows 預設 `opencode.cmd` |
| `OPENCODE_TIMEOUT_SEC` | OpenCode timeout 秒數，預設 1200 |
| `WORKFLOW_TEST_COMMAND` | Run Test step 使用的測試命令，預設 `python -m pytest` |

## Workflow Asset 目錄

```text
data/ai-workflow/
  workflows/*.workflow        # workflow 順序 / include manifest
  contracts/**/*.yaml         # step metadata，例如 retry、function、review mode
  steps/**/*.md               # skill / prompt markdown
  functions/**/*.py           # Python function assets
```

專案也可以放自己的 asset：

```text
<project>/.ai-workflow/
  workflows/
  contracts/
  steps/
  functions/
```

## 測試

日常檢查：

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

更多手動測試與 opt-in 測試請看：

```text
doc/TESTING.md
```

## 文件

詳細文件已集中放在 `doc/`：

| 文件 | 說明 |
|---|---|
| `doc/ARCHITECTURE.md` | 後端架構與模組責任 |
| `doc/SYSTEM_ARCHITECTURE.md` | 系統設計細節 |
| `doc/GENERAL_AUTO_DEVELOPMENT_WORKFLOW_USAGE.md` | General Auto Development 使用說明 |
| `doc/PYTHON_FUNCTION_ASSET_GUIDE.md` | Python Function Asset 寫法 |
| `doc/WORKFLOW_PYTHON_FUNCTION_GUIDE.md` | Workflow Python function 補充說明 |
| `doc/FRONTEND_STRUCTURE.md` | 前端 static/js 拆分結構 |
| `doc/TESTING.md` | 測試與手動驗證指令 |
| `doc/TODO.md` | 後續待辦 |

## 適合拿來做什麼

- 公司內部 AI Agent Web UI
- 可控的 Spec → Todo → Build → Test → Review 流程
- Regression Test Framework 產檔與驗證流程
- 讓較小模型透過固定 workflow、retry、validation 補足穩定性
- Qwen / OpenCode CLI 的 Web 化與流程化包裝
