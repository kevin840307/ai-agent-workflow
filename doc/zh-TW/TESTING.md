# 測試與真實 Agent 認證

## 確定性檢查

```powershell
python -m compileall -q app tests
python scripts/validate_workflow_assets.py
python -m pytest -q tests/test_stability_completion_v15.py
python -m pytest -q tests/test_unattended_stability_v16.py
python scripts/run_tests.py --mode all --isolate-all
```

建議使用隔離矩陣，因為部分舊 FastAPI／TestClient 測試刻意驗證 Process／Thread 生命週期，不適合全部共用同一個長生命週期 pytest Interpreter。

## V16 無人值守穩定性契約

V16 測試涵蓋：

- Connection Refused 分類與模型回線等待；
- Progress-aware Retry；
- Profile 驅動 Environment Preflight；
- Validation Profile Descriptor Stale；
- Atomic Delivery 與套用後驗證；
- 只有 Unattended Run 才自動 Restart Recovery；
- Stop／Cancel 只顯示一個結果；
- Simple Mode 與完整高度 UI 工作區。

## UI Geometry 與 Smoke

```powershell
python scripts/run_browser_ui_smoke.py
```

應在 1920×1080 與響應式寬度檢查：

- Run Center 的總覽／驗證 Tabs 固定；
- Validation 位於 Tabs 下方；
- 技術診斷可最大化；
- Agent／完整 Log 有可用高度；
- Patch Review Header 可見；
- Patch Workbench 的檔案清單／Diff 與執行產物的清單／預覽各自獨立捲動；
- Stop 只有一個 Dialog／狀態；
- 模型 Offline → Online；
- 大量 Event 不會卡住 UI。

## 故障注入情境

認證應涵蓋：Agent 未寫檔、寫一半後 Process Kill、Endpoint 斷線與恢復、Controller Restart、Session 遺失、Context Overflow、既有 Baseline Failure、Flaky Test、Protected Path 修改、外部修改原專案、Profile Stale、多 Session 並行、同專案 Writer 衝突、磁碟／資源錯誤、重複無進展、超過一般 Retry 但持續改善，以及 Final Apply 中斷。

## Real-Agent Matrix

```powershell
python scripts/run_real_agent_matrix.py --mode plan
python scripts/run_real_agent_matrix.py --mode self-prompt-test --execute
python scripts/run_real_agent_matrix.py --mode real --execute --agent qwen --parallel 1
```

追蹤：

- 使用者一次送出需求後完成率；
- 首次成功率；
- 自動修復後成功率；
- Retry／Session Rotation；
- Validation Profile 重用；
- Restart Recovery；
- 人工介入；
- False Success；
- Scope Violation；
- 原專案損壞。

正式目標：修復後成功率 ≥ 90%、外部驗證 ≥ 95%、Restart Resume ≥ 95%、人工介入 ≤ 10%、False Success = 0、交付 Scope Violation = 0、失敗 Run 損壞原專案 = 0。

Mock、Dry Run、Plan、Self-prompt 都不能當作真實模型認證。

### V19 本機 Qwen 驗收結果

- Prompt acceptance：10/10 通過。
- 真實 Agent matrix：10/10 通過。
- 修復後成功率：100%。
- 外部驗證通過率：100%。
- 人工介入率：0%。
- Scope violation：0。
- General 七排序單句需求：Workflow 完成、Agent 生成測試 7/7 通過。
- Adaptive 七排序單句需求：兩次自動修復測試目錄後完成、Agent 生成測試 71/71 通過。

證據位於 `reports/qwen-prompt-acceptance-v19.json`、`reports/qwen-real-acceptance-v19.json` 與 `reports/qwen-seven-sort-v19/`。七排序執行只把原始使用者需求交給 Agent；Controller 未生成產品原始碼或測試檔。

## Windows 本機 Agent Case

```powershell
.\scripts\run_local_qwen_cases.ps1 -Case all -Agent qwen -Workflow general-auto-development -Repeat 5
```

每個 Case 使用獨立 Project Path，並可搭配確定性 `validation.py`。`-DryRun` 只產生計畫，不呼叫 Qwen／OpenCode。

## 選用人工環境檢查

```powershell
$env:RUN_REAL_QWEN="1"
$env:RUN_REAL_QWEN_FULL="1"
$env:RUN_REAL_QWEN_STABILITY="1"
$env:RUN_CLEAN_REPO_SMOKE="1"
$env:RUN_PLAYWRIGHT_UI="1"
```

## 可重現的 UI／恢復故障注入

以下 Mock 情境只用於可重現的 UI 與恢復測試，不能算作真實 Agent 證據。

```powershell
# Scenario IDs: QWEN_MOCK_SCENARIO=fail_final_review_once, QWEN_MOCK_SCENARIO=generate_tests_no_files
$env:QWEN_MOCK="1"
$env:QWEN_MOCK_SCENARIO="fail_final_review_once"
python scripts/run_general_auto_development_e2e.py --scenario fail_final_review_once

$env:QWEN_MOCK_SCENARIO="generate_tests_no_files"
python -m pytest -q tests/test_release_and_ui_manual.py
```

使用真實 Qwen／OpenCode Endpoint 前，請清除 `QWEN_MOCK_SCENARIO`。

## V18 穩定性與故障注入測試

```bash
python -m pytest -q tests/test_reliability_v18.py
python scripts/run_chaos_matrix.py
python scripts/run_reliability_soak.py --iterations 200
python scripts/run_browser_ui_smoke.py --browser
```

矩陣涵蓋空白 Failure 正規化、量化修復進度、過期 Lease、重複 Attempt、模型 Circuit 狀態轉換、Flaky Test、Process Registry 清理、UI 狀態版本防倒退，以及單一捲軸瀏覽器幾何驗證。

## V20 無人職守交付與真實 Qwen Case

```powershell
python -m pytest -q tests/test_unattended_v20.py
python scripts/run_tests.py --isolate-all --file-timeout 240
python scripts/run_real_qwen_unattended_e2e.py
python scripts/run_real_qwen_unattended_e2e.py --parallel
```

V20 契約會在 Delivery 各個持久化邊界注入 Controller 中斷，驗證完整 Rollback、過期 Fencing Token 阻擋、舊 SQLite 升級、Endpoint／Model Circuit 隔離、專案內 Agent 設定、明確 Workflow Phase Metadata、右側收合狀態軌道與大型 Diff Dialog。

真實 Qwen 執行刻意維持 Opt-in。一般矩陣只驗證 E2E Runner／Case 契約；除非目標機器設定 `RUN_REAL_QWEN_UNATTENDED=1` 或 `RUN_REAL_QWEN_UNATTENDED_PARALLEL=1`，否則 `tests/test_real_qwen_unattended_manual.py` 會 Skip。

Controller 不得使用關鍵字表解析自由文字需求，以判斷 Intent、Risk、Complexity、Scope、Phase 或預期檔案／Symbol。Validation Script 產生器因此必須明確提供 `expectedFiles`，並可選擇提供 `expectedSymbols`。

## V21 Patch Review／Artifact 契約

```bash
python -m pytest -q tests/test_v21_patch_review_artifacts.py
python scripts/run_browser_ui_smoke.py --browser
```

V21 檢查：Run Center 無 Changes Tab、技術診斷無重複 Patch Review、Approval Hash 綁定與失效、Partial Patch 隔離重驗證、結構化 Reject Target、明確 Artifact Metadata、未知 Artifact 不做檔名／路徑推論、大型 Diff／Artifact 分段載入、側欄偏好記憶、儲存摘要，以及 1920×1080 下近全螢幕 Workbench、獨立捲動與 Focus Mode。

## V22 Artifact／Preview、Split Diff 與 Step Dialog 契約

```bash
python -m pytest -q tests/test_v22_artifact_diff_step_preview.py
python scripts/run_browser_ui_smoke.py --browser
```

V22 檢查 SQLite Projection 完整還原、舊 Run Artifact Metadata 一次性補建、真實 Storage Path Preview ID、文字／媒體預覽、二進位安全下載、工具目錄不進入 Diff／Atomic Delivery、專案 `.qwen`／`.opencode` 仍提供給 Agent cwd、Split Diff 精確等寬，以及保留 Step 上下文的獨立對應文件 Dialog。
