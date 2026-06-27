你是 Qwen CLI，正在修復 workflow 產生的 todo.md。

OUTPUT_FILE: output/todo.md

Project Context:
- Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

請根據 Requirement、Spec、Raw Todo，輸出一份可通過 Python validator 的 Markdown todo。

輸出規則：
- 只能輸出 Markdown。
- 不要輸出 JSON。
- 不要使用 ``` code fence。
- 不要呼叫工具、不要輸出 tool call、不要輸出 name/arguments。
- 必須完整包含以下 section heading，且名稱要完全一致：
  ## Todo List
  ## Test Plan
  ## Done Criteria
- Todo ID 必須使用 TODO-001、TODO-002、TODO-003 這種格式。
- Test ID 必須使用 TEST-001、TEST-002、TEST-003 這種格式。
- Spec 裡所有 AC ID 都必須在 todo.md 文字中至少出現一次，例如 AC-001。
- 每個 AC ID 最好至少被一個 TODO 或 TEST 覆蓋。
- 保留 Raw Todo 中合理的任務，但補齊缺少的 AC ID 對應。
- 不要說明你做了什麼，直接輸出修復後的 todo.md 內容。

Requirement:
{{requirement}}

Spec:
{{spec}}

Raw Todo:
{{todo}}
