# 文件索引

這個目錄是 Agent Workflow Web 的繁體中文文件。

## 建議閱讀順序

1. `AGENT_INSTALLATION.md` - 安裝 Qwen Code / OpenCode，並設定 CLI 路徑。
2. `AGENT_SLASH_COMMANDS.md` - 安裝專案用 `/wf` 與 `/wstep` 指令給 Qwen/OpenCode。
3. `AGENT_PROJECT_GUARD.md` - 理解 Qwen/OpenCode 的專案層級編輯限制。
4. `ADAPTIVE_AUTO_WORKFLOW.md` - 理解簡化版自動產生 / review / validation loop。
5. `WORKFLOW_METADATA.md` - 理解 `kind`、`protected`、`deletable` 行為。
6. `GENERAL_AUTO_DEVELOPMENT_WORKFLOW_USAGE.md` - 使用較完整的自動開發 workflow。
7. `PYTHON_FUNCTION_ASSET_GUIDE.md` - 撰寫可重用的 Python function asset。
8. `FRONTEND_STRUCTURE.md` - 維護 static frontend 拆分結構。
9. `TESTING.md` - 執行日常檢查與 opt-in 手動測試。
- [`SYSTEM_PRODUCTIZATION_V9.md`](SYSTEM_PRODUCTIZATION_V9.md) — V9 可靠性、風險核准、Checkpoint、Validator、Benchmark 與非阻塞 UI。
10. `SYSTEM_OPTIMIZATION_V8.md` - 查看統一狀態機、Session、SQLite Evidence、Run Center、Compact Artifacts 與智慧建議。
11. `WORKFLOW_OPTIMIZATION_V7.md` - 查看階段檔案 ownership、測試版面自動修復、timeout fresh session 與 Retry 額度強化。
12. `WORKFLOW_OPTIMIZATION_V6.md` - 查看實際專案路徑與 filesystem-first 執行基礎。

英文文件在 `../en/`。

See also: `doc/WORKFLOW_STABILITY_PLAN.md` for the stability score, failure-injection matrix, and isolated-workspace guard pattern.
