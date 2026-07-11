# Project Path Write Fix V5

## 問題

真實 Qwen / OpenCode Run 未指定 `patchMode` 時，後端預設使用 `review`。Agent 因此在下列隔離副本執行：

```text
<project>/.ai-workflow/runs/.../.workflow/isolated-workspace/agent-project
```

生成檔案不會立即出現在使用者選擇的正式專案目錄。

## 修正

- 預設 `patchMode` 改為 `auto_apply`。
- Agent cwd 預設就是使用者選擇的 Project Path。
- `.ai-workflow` 只保存 Run log、prompt、artifact、state 等控制器資料。
- `review` 與 `dry_run` 仍可透過 API 的 `patchMode` 或環境變數 `AIWF_DEFAULT_PATCH_MODE` 明確啟用。
- 舊隔離 Run 在停止後可透過 Run Detail 的 **Apply to Project** 將生成檔案套用回正式專案。
- UI 顯示原始 Project Path，不再把隔離 cwd 當成使用者選擇的專案。

## 預設行為

```text
Project Path: C:\Projects\sort
Agent cwd:    C:\Projects\sort
Run data:     C:\Projects\sort\.ai-workflow\runs\...
```

## 使用隔離審核模式

```powershell
$env:AIWF_DEFAULT_PATCH_MODE = "review"
```

或建立 Run 時傳入：

```json
{
  "patchMode": "review"
}
```
