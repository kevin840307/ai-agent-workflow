# 快速開始

## 1. 環境需求

- Python 3.10 以上
- Qwen Code 與／或 OpenCode
- 可寫入的專案資料夾
- CLI 所需的本機模型 Endpoint

## 2. 啟動平台

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

開啟 `http://127.0.0.1:8000`。建議只使用一個 uvicorn worker。不同 Project／Session 可共用 Provider Slot 並行，同一專案仍只保留一個 Writer。

## 3. 先執行 Setup Smoke

隔離 Smoke Test 會檢查 Controller 權限、CLI、模型回覆、新 Session，以及 Agent 是否真的能用自己的 Tool 寫檔。能力結果保存於 Controller 資料目錄，後續只會保守縮小 Task／Prompt，不會擴大權限。

## 4. Simple Mode：第一次無人值守執行

1. 選擇 Project Path。
2. 確認模型狀態為「已連線」；也可點擊狀態立即重查。
3. 輸入一句明確需求。
4. 按開始。

Simple Mode 會自動完成：

```text
理解專案 → 建立／重用 Validation Profile → 建立 Baseline
→ 讓 Qwen／OpenCode 在有效 Project Path cwd 自己修改
→ 驗證與修復 → Session／Process 恢復 → 原子交付
```

主畫面只保留「總覽」與「驗證」。總覽顯示變更摘要並開啟近全螢幕 Patch Review Workbench；驗證顯示是否真正執行、命令、Exit Code、耗時、Required／Blocks Apply、Baseline 與相關 Evidence。只有需要除錯時才打開「技術診斷」，查看 Agent 原始輸出、完整 Log、執行產物、修復策略、Checkpoint、Session／Process、Delivery Journal 與 Retry。

## 5. Project Validation Profile

第一次使用專案時，平台會偵測既有 Build／Test／Lint／Type Check，並把 Draft Profile 存在 Controller 資料目錄，不污染使用者專案。點擊「專案驗證」即可確認與實際驗證。成功一次為 `Verified`，成功三次為 `Trusted`；Build／Test 描述檔變更後會標記 `Stale`，需重新驗證。

## 6. Advanced Mode

進階模式可選 Workflow／Profile／Thinking、切換無人值守、編輯 Project Validation Profile、設定專案相對路徑的不可變更 Validation Script、查看 Session，或使用 Review Patch。

Qwen／OpenCode 一律以有效工作區作為 cwd。一般模式就是使用者選擇的 Project Path；隔離無人值守模式則使用保留專案設定的驗證副本，因此 `.qwen/settings.json`、`.qwen/QWEN.md`、`opencode.json` 仍會被自然載入。

## 7. 安裝 `/wf`、`/wstep`

```powershell
python scripts/install_agent_commands.py --target all --scope project
```

Web UI、`/wf`、`/wstep` 共用同一套 Workflow Kernel。

## 常用環境變數

| 變數 | 用途 |
|---|---|
| `QWEN_BIN`／`OPENCODE_BIN` | CLI 路徑 |
| `QWEN_TIMEOUT_SEC`／`OPENCODE_TIMEOUT_SEC` | 單次 Agent 總逾時 |
| `AIWF_AGENT_STALL_TIMEOUT_SEC` | 無輸出卡住判定，預設 300 秒 |
| `AIWF_AGENT_HEARTBEAT_SEC` | 心跳間隔，預設 60 秒 |
| `AIWF_AGENT_MAX_CONCURRENCY` | Provider 預設 Slot，預設 2 |
| `AIWF_QWEN_MAX_CONCURRENCY` | Qwen 專用 Slot |
| `AIWF_OPENCODE_MAX_CONCURRENCY` | OpenCode 專用 Slot |
| `AIWF_VALIDATOR_MAX_CONCURRENCY` | Validator Slot |
