# Real Qwen Local Cases

每個資料夾都是一個可獨立執行的真實 Agent 測試：

- `prompt.txt`：實際送給 Qwen 的單行需求。
- `project_seed/`：Run 開始前的專案內容。
- `validation.py`：完成後必須真正執行且 Exit Code 為 0。
- `case.json`：Case 名稱與預期檔案。

請使用專案根目錄的 `scripts/run_local_qwen_cases.py` 或
`scripts/run_local_qwen_cases.ps1`，不要直接修改 Case 內容。
