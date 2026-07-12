# 維運與穩定性

## 併發與資源

Provider Slot 依 Agent／Provider 管理，不依 Session 鎖死。不同 Project／Session 可並行，同一原始專案仍保留一個 Writer Lock。只有一個顯存有限的 Endpoint 時，建議把模型併發設為 1；Validator 使用獨立 Slot。

平台不預設啟用多 Agent Review，會重用增量 Index／Profile、傳送 Task 範圍 Context，並先跑 Focused Check 再跑 Full Validation。

## 模型連線與回線

UI 會持續探測可辨識的模型 Endpoint：

- Online：較低頻背景檢查；
- Offline：畫面可見時約每 2.5 秒檢查；
- Unknown／CLI-only：保守檢查；
- 分頁隱藏：降低輪詢頻率。

點擊模型狀態可立即重查；瀏覽器回到前景或網路恢復也會觸發。Workflow EventSource 不會在暫時錯誤時永久關閉，回線後會重新同步 Run。

無人值守 Run 遇到已分類的 Transport／Connection Refused 時，會先低頻等待模型恢復，再開始下一次 Agent Attempt；等待不會被算成重複實作失敗。

## Watchdog

Supervisor 追蹤 stdout／stderr 活動並產生 Heartbeat。模型只是慢速運算時不會被誤殺，只有無輸出 Stall 或總 Timeout 才結束 Process。先 Graceful Stop，再終止 Process Tree。

## Recovery Budget

Workflow 可以保留高 `maxRetries` 給小模型，但實際執行由可設定的累積 Budget 控制：

| 範圍 | 預設 |
|---|---:|
| 整個 Run 失敗 | 40 |
| 單一 Step 失敗 | 24 |
| 單一 Task 失敗 | 12 |
| 同 Failure Class | 12 |
| 同 Fingerprint | 9 |
| Wall-clock | 60 分鐘 |
| Fresh Session | 同類失敗每 3 次 |

Progress-aware Recovery 不會把測試失敗持續減少視為無效循環；Failure 與 Progress 完全相同時才更早換策略／Session。

## Project Validation Profile 維運

Profile 保存於 Controller AI Workflow 資料目錄，不改變 Git Status。無人值守前應驗證 Draft／Stale Profile。支援的 Build／Test／Validation Descriptor Fingerprint 改變後，Profile 會自動變 Stale。

Profile 可宣告必要 Command、環境變數及 Service Health Check。缺少必要環境時會在 Agent 修改前阻擋執行。

## Baseline 與老舊專案

實作前先執行 Baseline。原本就存在的失敗會留下 Evidence；最後只阻擋新增／惡化的失敗與未完成 Acceptance，不會自動要求 Agent 修掉所有無關歷史問題。

## 隔離工作區與原子交付

無人值守預設使用 Atomic Apply。Agent 在隔離有效 Project Path 工作；交付前檢查原始 Source Fingerprint，只複製已驗證的 Agent 變更，套用後再跑 Fast Validation，退化時回滾。Runtime Artifact／Profile 仍由 Controller 管理。

## Durable Restart Recovery

Controller 啟動時會把遺留 Running 狀態標為 Interrupted，再只自動恢復具有安全 Restart Metadata 的 Unattended Run。一般手動／進階 Run 仍由使用者控制。Project Lock 與持久化狀態避免重複 Writer。

## UI 維運

- Run Center 與技術診斷可以收合／重開。
- 技術診斷可最大化到整個 Viewport。
- Agent、完整 Log、修復策略、驗證、Patch 檔案／Diff，以及執行產物清單／預覽都有獨立捲動。
- 大量 Log／Event 會批次渲染並限制瀏覽器顯示量；完整 Evidence 仍保存於 Artifact／Event。
- Stop 在瀏覽器端具冪等保護，只產生一個取消結果。

## 備份與診斷

備份 `data/store.sqlite3`、`data/settings.json`、全域 Workflow Asset、Controller Project Profile，以及需要保留的專案 `.ai-workflow/runs`。調查時先看 Overview，再使用技術診斷、Debug Bundle、一致性檢查、Artifact Repair、Run Comparison 與 Benchmark。

## 安全發版流程

```powershell
python -m compileall -q app tests
python scripts/validate_workflow_assets.py
python scripts/run_tests.py --mode all --isolate-all
python scripts/run_production_acceptance.py
```

宣稱真實模型認證前，仍須在目標 Windows／Qwen／OpenCode 環境執行 Real-Agent Matrix。

## V18 無人值守穩定性保護

V18 新增四個由 Controller 管理、且不會修改專案來源碼的保護：

- **Run Lease：**同一時間只有一個有效 Controller 可以擁有 Run；過期 Lease 可於重啟後接管。
- **冪等 Attempt：**已完成的 Step Attempt 不會因重新連線或重啟而再執行一次。
- **模型 Circuit Breaker：**Endpoint 連續失敗後暫停新的 Agent 呼叫；恢復時只允許一個 Half-open Probe。
- **Process Registry：**統一記錄 Agent 與 Validation Process，Controller 啟動時會清理失去有效擁有者的子程序。

Pilot 前建議執行：

```bash
python scripts/run_chaos_matrix.py
python scripts/run_reliability_soak.py --iterations 200
python scripts/run_browser_ui_smoke.py --browser
```

隔夜測試可提高 Soak 次數。真實 Qwen／OpenCode 認證仍為獨立、明確啟用的測試。
