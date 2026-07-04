You are preparing a project for an automated development workflow.

Requirement:
{{requirement}}

Project path:
{{project_path}}

Deterministic project index:
{{project_index}}

Detected project profile:
{{project_profile}}

Visible project files:
{{project_overview}}

Read the current project structure before planning any implementation.

Required checks:
- If the project is not empty, infer the existing language, framework, source layout, test layout, and naming style from the files.
- Check whether project-local agent settings exist:
  - `.qwen/settings.json`
  - `opencode.json`
- Treat those settings as project-local runtime context only. Do not copy them to global settings.
- Read files anywhere when needed for understanding, including shared reference files outside Project path.
- All generated edits must stay inside Project path. Do not write to reference folders, sibling projects, global agent settings, or user home config.
- Treat paths outside Project path as read-only context.
- If `architecture.md` already exists, update it only when it is incomplete or stale.
- If `architecture.md` does not exist, create it in the project root.

Do not ask the user questions. If details are missing, use reasonable assumptions and record them under Implementation Rules or Unknowns.

Use Qwen/OpenCode edit/write tools directly. Respond only with a brief summary.

Required file:
