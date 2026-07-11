# Workflow Optimization V6

本版針對實際測試的 **General Auto Development** 與 **Adaptive Auto Workflow**，統一修正執行路徑、輸出解析、Retry、Rollback、驗證與 Review 行為。

## 正式專案路徑

正常 `auto_apply` 模式下，使用者選擇的 Project Path 就是 Qwen／OpenCode 的實際 cwd 與唯一寫入根目錄。

```text
Project Path： C:\Projects\sort2
Agent cwd：    C:\Projects\sort2
生成檔案：     C:\Projects\sort2\...
執行資料：     C:\Projects\sort2\.ai-workflow\runs\...
```

`.ai-workflow` 只保存 prompt、log、state、evidence 與 report。正式 source、test、config 不可生成在 run workspace。

只有明確選擇 `review` 或 `dry_run` 時才使用隔離副本。

## Build 判定

- 以實際 filesystem diff 為主要依據。
- Agent 已完成寫檔，但最後摘要格式錯誤或 timeout 時，不再直接刪除成果。
- `Successfully overwrote file...` 等 tool result 只顯示為狀態，不會被當成錯誤或 Step artifact。
- 候選檔案會先接受 deterministic validation，再決定通過或修復。

## Rollback 與 Session

只在測試失敗、validation 失敗、保護路徑異常或必要檔案缺失等確定性錯誤時 rollback。

Parser、summary、session、context 類錯誤不會先刪除已生成的候選成果。若真的 rollback，下一次 Agent 呼叫強制使用新 Session，避免模型記憶與實際檔案不一致。

## Retry

- 失敗來源 Step 與 Retry Target 分開記錄。
- Build 的錯誤不再算成 Planner 的錯誤。
- Review JSON 格式錯誤或 Review 修改檔案，只重跑 Review。
- Build／Test 失敗修復目前 Task。
- 只有明確的 plan/spec conflict 才重新規劃。
- 相同失敗重複時提早停止。
- 一般 Retry 上限由 99 降為 6。
- 每個 Task 有獨立 timeout，不再共用整個 Task Loop 的倒數時間。

## Planner 與 Review

Planner／Review 使用 fresh session，並由 Controller 施加唯讀 snapshot。若它們修改專案，修改會還原並被分類為唯讀違規。

Review 要回傳結構化 JSON，包含 Acceptance Criteria 與對應 Evidence。沒有完整 evidence 時，Controller 會限制可信度，不接受模型自行宣稱 `confidence: 1.0` 作為唯一依據。

## 任務複雜度

Controller 依需求與專案規模分為：

| Profile | Task 上限 | 適用情境 |
|---|---:|---|
| tiny | 2 | 單一函式、小修正、小檔案變更 |
| standard | 5 | 跨數個檔案、功能與測試 |
| complex | 10 | 跨模組／服務、migration、架構調整 |

Planner 必須採用 minimum sufficient implementation，不可自行增加重複 module、額外 example、文件或未要求功能。

## Python 驗證

驗證順序：

1. 指定 validation script
2. pytest
3. `run_tests.py`
4. 有 Python source 但無可執行測試：`FAIL / VALIDATION_NOT_EXECUTED`
5. 非 Python 任務：明確 `SKIPPED`

Final hygiene gate 會檢查：

- 重複 public implementation；
- 根目錄與 `tests/` 重複測試；
- 測試檔重新實作 production function；
- 多套不必要的 test entry point。

Final Gate 的 validation status 直接取自真實 validation artifact，避免 pytest 已 PASS，報告卻顯示 SKIPPED。

## Failure Feedback

只保留最近三筆精簡 failure feedback，單筆錯誤內容會截斷。完整資訊仍在 run log，但不會再把整份 source code 與重複 tool transcript 塞回 Planner prompt。
