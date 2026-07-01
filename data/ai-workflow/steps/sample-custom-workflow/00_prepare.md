你是 Qwen CLI，現在執行 workflow 的第 0 步：理解既有專案架構，並建立或更新工作目錄的 architecture.md。
OUTPUT_FILE: output/architecture.md

Project Context:
- Working Directory / Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

使用者需求:
{{requirement}}

Project File Overview:
{{project_overview}}

Existing architecture.md in Working Directory:
{{architecture}}

任務:
- 工作目錄就是 Project Path，也是 Qwen 執行時的 cwd。
- architecture.md 必須建立或更新在工作目錄根層：`{{project_path}}/architecture.md`。
- 不要把 architecture.md 寫到 Workflow Workspace。
- 不要把 architecture.md 寫到 `.qwen-workflow`。
- 如果這是既有專案，請根據檔案清單與命名推論目前架構。
- 如果工作目錄已經有 architecture.md，請保留仍正確的資訊，更新過期或缺漏的部分。
- 如果目前資訊不足，請寫明 Unknowns，不要假裝知道。
- architecture.md 要幫後續 Spec、Todo、Build、Test 理解專案邊界、模組分層、測試位置、執行方式。

硬性規則:
- 只輸出最終 artifact 內容，不要輸出 JSON。
- 不要輸出 Markdown code fence。
- 必須輸出 `FILE: architecture.md`。
- `FILE` 必須剛好是 `architecture.md`，不要加子資料夾。
- `FILE` 是相對於工作目錄 / Project Path 的路徑，不要使用絕對路徑。
- 不要修改任何產品程式碼或測試碼。
- `CONTENT` 必須是完整的 architecture.md 內容。

建議內容:
- # Architecture
- ## Overview
- ## Project Structure
- ## Runtime And Entry Points
- ## Data Flow
- ## Testing Strategy
- ## Conventions
- ## Unknowns
- ## Update Notes

輸出格式:

Status: DONE

FILE: architecture.md
CONTENT:
# Architecture

...
END_FILE
