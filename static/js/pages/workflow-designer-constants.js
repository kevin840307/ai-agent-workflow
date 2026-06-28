// Shared static data for the workflow designer.
// Keep large option/preset lists out of workflow-designer.js so the page logic
// stays focused on state, rendering, and event handling.

export const StepTypes = [
  ["ai", "AI Prompt"],
  ["validation", "Validation Function"],
  ["review", "Review"],
  ["gate", "Human Gate"],
  ["command", "Command Prompt"],
  ["python", "Python Function"],
  ["manual", "Manual Approval"],
];

export const SourceTypes = [
  ["command", "Command"],
  ["skill_path", "Skill Path"],
  ["prompt_file", "Prompt File"],
  ["inline_prompt", "Inline Prompt"],
  ["context_file", "Context File"],
  ["artifact", "Previous Artifact"],
];

export const ReviewModes = [
  ["none", "No AI Review"],
  ["current_session", "Current Session Review"],
  ["new_agent", "New Agent Review"],
  ["multi_agent", "Multi-Agent Review"],
];

export const FailActions = [
  ["same_step", "Retry same step"],
  ["selected_step", "Retry from selected step"],
  ["previous_step", "Retry from previous step"],
  ["stop", "Stop immediately"],
];

export const BuiltInPromptParams = [
  { key: "requirement", label: "Requirement", description: "Main user input from the runner composer.", sample: "Create a controllable agent workflow UI." },
  { key: "project_path", label: "Project Path", description: "Current project folder path.", sample: "C:\\Users\\kevin\\sort" },
  { key: "workspace_path", label: "Workspace Path", description: "Workflow run workspace path.", sample: "runs/workflow-001" },
  { key: "project_overview", label: "Project Overview", description: "Auto-generated overview of the project files and folders.", sample: "Project files:\n- app/main.py\n- static/js/pages/workflow-designer.js" },
  { key: "architecture", label: "Architecture", description: "Content of architecture.md from the selected project path.", sample: "# Architecture\nFastAPI backend with static frontend." },
  { key: "spec", label: "Spec", description: "Rendered content from output/spec.md.", sample: "## Goal\nBuild the requested workflow feature." },
  { key: "spec_review", label: "Spec Review", description: "Rendered content from output/spec-review.md.", sample: "Status: PASS" },
  { key: "todo", label: "Todo", description: "Rendered content from output/todo.md.", sample: "## Todo List\n- TODO-001 Implement UI." },
  { key: "todo_review", label: "Todo Review", description: "Rendered content from output/todo-review.md.", sample: "Status: PASS" },
  { key: "test_plan", label: "Test Plan", description: "Rendered content from output/test-plan.md.", sample: "## Test Plan\n- TEST-001 Verify build output." },
  { key: "test_result", label: "Test Result", description: "Rendered content from output/test-result.md.", sample: "Status: FAIL\nAssertionError: expected file missing." },
  { key: "build_result", label: "Build Result", description: "Rendered content from output/build-result.md.", sample: "FILE: app/main.py\nCONTENT:\n..." },
  { key: "final_review", label: "Final Review", description: "Rendered content from output/final-review.md.", sample: "Status: PASS" },
  { key: "raw_spec", label: "Raw Spec", description: "Alias of output/spec.md, kept for older templates.", sample: "## Goal\nBuild the requested workflow feature." },
  { key: "answers", label: "Answers", description: "User answers collected from previous workflow interaction.", sample: "Use Python and FastAPI." },
  { key: "guidance", label: "Guidance", description: "User guidance added during the workflow.", sample: "Keep the implementation minimal and maintainable." },
  { key: "last_error", label: "Last Error", description: "Latest validation, review, timeout, or runner error.", sample: "Missing Acceptance Criteria section." },
  { key: "failure_feedback", label: "Failure Feedback", description: "Failure feedback accumulated for the retry target step.", sample: "Retry 1/2 from build: tests failed because app/main.py was not updated." },
  { key: "step_output", label: "Step Output", description: "Current step output text when available.", sample: "Step completed successfully." },
];

export const TemplatePresets = {
  generate_spec: {
    path: "prompts/01_spec.md",
    filename: "spec.md",
    content: `你是 Qwen CLI，在這個系統中扮演「可重現的產物撰寫器」。請根據下方 Requirement 產生產品規格文件。

FILENAME: spec.md

Project Context:
- Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

你的完整回覆會被原封不動存成 spec.md。

硬性輸出契約：
- 只能輸出 Markdown。
- 不要輸出 JSON。
- 不要使用 \`\`\` code fence。
- 不要解釋你正在做什麼。
- 忽略此 Qwen session 先前所有對話，只能使用下方 Requirement。
- 內容必須只根據 Requirement。

Requirement:
{{requirement}}`,
  },
  review_spec: {
    path: "prompts/02_review_spec.md",
    filename: "spec-review.md",
    content: `你是 Qwen CLI，在這個系統中扮演規格審查者。請審查 spec.md 是否符合 Requirement。

FILENAME: spec-review.md

Project Context:
- Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

你的完整回覆會被原封不動存成 spec-review.md。

輸出規則：
- 只能輸出 Markdown。
- 第一個非標題狀態行必須完全是：
Status: PASS

如果 spec 不完整或不符合 Requirement，請使用：
Status: FAIL

Requirement:
{{requirement}}

Spec:
{{spec}}`,
  },
  generate_todo: {
    path: "prompts/03_todo.md",
    filename: "todo.md",
    content: `你是 Qwen CLI，在這個系統中扮演「可重現的實作計畫撰寫器」。請根據 Requirement 與 Spec 產生 todo plan。

FILENAME: todo.md

Project Context:
- Project Path: {{project_path}}
- Workflow Workspace: {{workspace_path}}

你的完整回覆會被原封不動存成 todo.md。

硬性輸出契約：
- 只能輸出 Markdown。
- 不要輸出 JSON。
- 不要使用 \`\`\` code fence。

Requirement:
{{requirement}}

Spec:
{{spec}}`,
  },
};

