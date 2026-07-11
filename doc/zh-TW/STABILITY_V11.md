# 穩定性 V11

V11 專注於 Retry 狀態一致性、既有專案測試版面、重啟提示、變更去重，以及 Qwen／OpenCode 互動模式中的 `/wf`、`/wstep`。

## Runtime 穩定性

- 專案原本存在的根目錄 pytest，例如 `test_sorts.py`，允許 Generate Tests 更新。
- 新產生的 pytest 仍預設必須放在 `tests/`，Build／Test ownership 不放寬。
- Retry 與 Final Gate 可安全處理「Store 回傳同一個可變 Run 物件」的情況。
- Retry reset 先建立深層快照，再同步穩定 Run，避免 `workspace`／`steps` 被自己清空。
- Final Completion Gate 使用最新持久化 Run 的安全快照。

## UI 穩定性

- 服務重啟提示只在 Current Action 顯示一次，不再於下方再出現大型失敗卡。
- `.\\sorts.py` 與 `sorts.py` 等路徑別名會合併成同一筆變更。
- 多檔案 Changes 的 `+/-` 只在檔案導覽顯示一次；右側只顯示「預覽」與真正 Diff，不再像重複兩筆。

## 互動模式 `/wf` 與 `/wstep`

安裝器會把目前 Python 與穩定 Launcher 的絕對路徑寫入 Qwen Code／OpenCode command，因此可以從目標專案啟動 Agent，不必切回 Controller 根目錄。

```bash
python scripts/install_agent_commands.py --target all --scope project --project <project>
```

安裝時會從目標專案執行兩條非破壞性 dry-run；Production Acceptance 也會執行同一檢查。

Command template 保持目前官方格式：

- Qwen Code：`.qwen/commands/*.md`、`{{args}}`、`!{command}`。
- OpenCode：`.opencode/commands/*.md`、`$ARGUMENTS`、``!`command` ``。

真正確認 TUI 輸入 `/` 後看得到命令，仍需在已安裝 Qwen Code／OpenCode 的 Windows 目標機執行。
