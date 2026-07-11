# Workflow Optimization V7

V7 針對 General Auto Development 與 Adaptive Auto Workflow 真實執行後發現的問題，補上可由 Controller 安全處理的確定性修復，避免只是偵測到錯誤後又反覆呼叫 AI。

## 主要改善

- 正常 `auto_apply` 模式仍直接以使用者選擇的 Project Path 作為 Agent cwd 與寫入根目錄。
- Build 只保留 production file；若模型同時建立測試檔，只精準還原錯誤階段的測試檔。
- Generate Tests 只保留 `tests/**`；若模型修改 production file，只還原越權修改。
- pytest 前自動檢查 root `test_*.py` 與 `tests/` 重複問題。
- 只會刪除「本次 Run 新增」且能確定為重複或空白的 root test；使用者原有檔案不會自動刪除。
- `import file mismatch` 分類為 `TEST_LAYOUT_CONFLICT`，先由程式清理並自動重跑 pytest，不消耗 AI Retry。
- Agent timeout 後改用 fresh session，不再連續 resume 同一個已卡住的 Session。
- Retry 次數記在真正失敗的 Step，而不是被回跳的修復目標。
- Step 成功後重置連續失敗 streak，但保留累積嘗試次數供報表查看。
- Failure feedback 增加明確 Stop condition，例如 pytest/validation exit code 必須為 0。
- Planner、Build、Review 的預設 Retry 額度進一步縮小，確定性修復不占用 AI Retry。
- Tiny 任務禁止自行擴大公開 API、重複 module、額外 example 或重複測試入口。

完整技術說明請見 [`../WORKFLOW_OPTIMIZATION_V7.md`](../WORKFLOW_OPTIMIZATION_V7.md)。
