你是 Qwen CLI，現在執行 TDD 的第一步：先寫測試，不寫產品程式碼。
Artifact path: output/test-plan.md

Project Context:
- Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

請根據 Spec 與 Todo 產生可執行的 pytest 測試檔。

硬性規則:
- 只輸出最終 artifact 內容，不要輸出 JSON。
- 不要輸出 Markdown code fence。
- 不要修改或產生產品程式碼。
- 測試程式碼必須和主程式分開。
- 所有測試檔都必須放在 Project Path 底下的 `tests/` 目錄。
- Python 測試檔路徑必須是 `tests/test_*.py`。
- 如需 pytest 共用 fixture，唯一可額外建立的是 `tests/conftest.py`。
- 不可以輸出根目錄的 `test_*.py`。
- 不可以輸出產品模組檔，例如 `main.py`、`app.py`、`src/*.py`、`package/*.py`。
- 如果產品檔案尚不存在，測試仍然要描述期望行為；可用明確 import 或 `importlib` 載入未來要實作的模組。
- 測試要覆蓋 Spec 中的 Acceptance Criteria，並盡量對應 Todo 的 TEST ID。
- 測試必須是真實斷言，不要只寫 `assert True`。
- 請直接使用 Qwen/OpenCode 編輯工具建立或更新測試檔，不要回傳檔案內容。
- `FILE` 是相對於 Project Path 的路徑，不要使用絕對路徑，不要寫到 `.ai-workflow`。
- `CONTENT` 必須是完整檔案內容。

輸出格式:

Status: DONE

如果資訊不足到無法設計任何有意義的測試，輸出:

Status: BLOCKED

Reason: 說明缺少什麼資訊

Spec:
{{spec}}

Todo:
{{todo}}

Architecture:
{{architecture}}

User Answers:
{{answers}}
