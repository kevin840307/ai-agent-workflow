Continue the same CLI coding session and complete this SOP task.

User request:
{{requirement_brief}}

SPEC to satisfy:
{{spec}}

Current task:
{{current_task}}

Prompt to type into Qwen/OpenCode:
{{current_task_prompt}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Retry feedback for this task, if any:
{{current_task_failure_feedback}}

Validation script, if provided:
{{validation_script}}

Do:
- Directly edit real files inside the selected project.
- Complete only the current task and required dependencies.
- Use the minimum sufficient implementation; do not add unrequested public parameters, duplicate modules, examples, or documentation.
- Preserve previous valid task work when editing shared files.
- Do not create or modify tests in Build; the Generate Tests step owns `tests/`.
- When this is a repair retry, fix only the concrete failure feedback and keep working code intact.
- Do not edit workflow/run files, validation scripts, `.git`, `.qwen`, `.qwen-workflow`, `.ai-workflow`, or files outside the project.
- Do not return tool-call JSON, FILE blocks, code fences, shell scripts, or prompt explanations.

Return a short Markdown summary with changed files, tests added/updated, and what was done.
