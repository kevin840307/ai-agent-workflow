# Production Readiness V10

V10 將「完成」定義為不可繞過的證據契約，適用於本機或公司內部單機部署。

## 穩定性保證

- 成功由實際檔案差異與確定性證據決定，不相信 Agent 口頭回覆。
- Required 使用者驗證檔在 Run 建立時解析、計算 SHA-256、設為唯讀、限制 Timeout，且每次修復後都重跑同一份檔案。
- Required 驗證缺檔、被改動、被阻擋、逾時或 Exit Code 非 0，皆不可顯示 PASS。
- Retry 只回到真正負責的 Task／Step；已完成 Task 由 Checkpoint 保留。
- Rollback、Timeout、Context Handoff 或檔案還原後，使用 Fresh Session 並注入目前真實檔案狀態。
- Final Completion Gate 重新讀取 SQLite 最新狀態，要求測試、必要驗證、Task、Step 與 Policy 全部符合條件。
- Production 測試矩陣讓每個測試檔使用獨立 pytest 行程，避免背景 Task teardown 污染其他案例。

## 產品只提供三個 Workflow

1. Adaptive Auto Workflow
2. General Auto Development
3. Security Vulnerability Scan

內部 Asset／Plugin 仍可擴充，但未支援的自訂 Workflow 不會出現在產品清單。

## UI 使用流程

- 環境提醒小型、非阻塞、可關閉，並記住關閉狀態。
- Changes 只保留一層逐檔檢視，使用真正行級 Diff 計算 +/-。
- 進階 Patch Review 提供搜尋、勾選、單欄／並排差異、核准與選擇性套用。
- Console、原始 Prompt、Artifact Index、Repair Policy 與 Debug 資料集中在可關閉的「技術診斷」抽屜。

## 部署範圍

V10 可用於受控的本機／公司內部單機 Production，使用單一 FastAPI worker 與 SQLite WAL。若要公開上網或多人租戶使用，仍需依公司環境補上身分驗證、授權、Secret 管理、網路防護與集中式 Audit 保存。
