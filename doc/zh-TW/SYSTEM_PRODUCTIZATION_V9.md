# 系統產品化 V9

V9 的目標是把 AI Workflow Controller 從「可以跑 Workflow」提升成「可長時間執行、失敗可恢復、一般使用者看得懂、進階使用者仍能完整控制」的本機產品。

## 一般使用流程

```text
選擇專案
→ 輸入需求
→ 需要時才展開／套用精簡建議
→ 開始執行
→ 查看目前動作與時間線
→ 查看變更與驗證
→ 高風險 Patch 才需要核准／套用
→ 只有除錯時才開啟技術診斷
```

## UI 不再阻擋主要內容

- 系統建議縮成 Composer 工具列中的小型建議圖示／膠囊，說明內容以 Popover 展開，可收合或關閉。
- 環境提示只在必要條件未完成時顯示；Context Window 等非阻擋建議留在 Setup Wizard／System Health。
- `runResultPanel` 改成不參與 Grid 排版的可關閉小型提示；成功後自動隱藏，不再把訊息區往上擠。
- Modal 與技術診斷抽屜均支援 X、點擊背景與 Escape 關閉。

## 變更與 Patch 審核

一般使用者使用「變更」頁面：

- 依新增／修改／刪除篩選；
- 顯示檔案由哪個 Task 產生；
- 以行號、顏色顯示新增與刪除；
- 顯示可能超出需求的 Scope 警告；
- 清楚標示變更已直接寫入，或仍在隔離 Patch 等待核准。

進階使用者從「技術診斷 → Patch 審核」操作：

- 逐檔勾選；
- 並排／單欄切換；
- 查看核准狀態；
- 只把選取檔案套用回原始 Project Path；
- Raw Patch 仍保留，但不再是一般使用者的預設畫面。

## Agent 與模型抽象化

Qwen、OpenCode 與未來 Provider 共用 Agent Adapter：

```text
Session 建立／恢復
Streaming
取消
唯讀能力
寫檔工具能力
錯誤分類
Usage／Capability metadata
```

模型 Profile：

- `small`：短 Prompt、小 Task；
- `normal`：一般本機開發；
- `strong`：跨模組與較大任務。

Prompt 超過模型預算時，Controller 只保留目標、目前 Task、最近驗證與最新錯誤，不再無限制累積完整歷史。

## Context Handoff

當 Context 超限或自動壓縮無法繼續時，Controller 會產生結構化交接：

- 需求目標；
- 目前 Task；
- 已完成 Task；
- 已接受的檔案；
- 最新測試／驗證；
- Typed Error；
- 限制與下一步。

接著由 Fresh Session 從原 Task 繼續，不重新塞入整段對話。

## Task Checkpoint

每個通過驗證的 Task 可建立可還原 Checkpoint。Checkpoint 有單檔、總容量與保留數量限制。後續 Task 失敗時只回到最近完成的 Task，不重做前面工作。

## 風險與核准

| 風險 | 預設策略 |
|---|---|
| Low | 直接修改正式 Project，自動完成 |
| Medium | 直接修改，但每個 Task 建立 Checkpoint |
| High | 隔離 Workspace，套用前核准 |
| Critical | 只產 Plan／Patch，不自動套用 |

Run Center 與 Patch 審核都能執行核准、拒絕與選擇性套用。

## Scope Control

最終結果會指出未要求的 README、Example、重複入口、公開 API 擴張等 Scope Delta。系統不會因為 AI 判斷就任意刪除使用者原有檔案；只有可證明屬於本次 Run 的安全規則或使用者核准後才清理。

## Validator Plugins

統一支援：

- Python／pytest；
- Maven／Gradle；
- .NET；
- Node；
- YAML／XML；
- SQL；
- Docker／Kubernetes；
- 自訂指令。

所有結果統一成狀態、命令、Exit Code、stdout/stderr 摘要與 Evidence。

## Release 與 Migration

V9 提供 App、Database、Workflow、Config Schema 版本。升級前請閱讀：

```text
CHANGELOG.md
UPGRADE.md
MIGRATIONS.md
```

## 固定 Benchmark

內建十個案例：

```text
BENCH-001 單檔新增
BENCH-002 多檔功能
BENCH-003 修復 failing test
BENCH-004 重構但 public API 不變
BENCH-005 Agent timeout recovery
BENCH-006 Session 遺失 recovery
BENCH-007 Context handoff
BENCH-008 Controller restart
BENCH-009 Project lock conflict
BENCH-010 Scope expansion detection
```

安全 Dry Run：

```bash
python scripts/run_productization_benchmarks.py
```

真實 Agent 執行必須明確指定：

```bash
python scripts/run_productization_benchmarks.py --execute --real
```

## 新增 API

```text
GET  /api/productization/version
GET  /api/productization/upgrade-readiness
GET  /api/productization/model-profiles
GET  /api/productization/validators
POST /api/productization/validators/run
GET  /api/benchmarks/catalog
GET  /api/benchmarks/summary
```

## 測試原則

V9 自動測試涵蓋模型能力、風險、Scope、Context Handoff、Task Checkpoint、Validator、Agent Adapter、Release、Benchmark、Approval 與非阻塞 UI。真實 Windows Qwen／OpenCode 與瀏覽器 E2E 仍需在使用者本機明確啟用。
