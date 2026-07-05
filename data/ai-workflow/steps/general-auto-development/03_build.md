Continue the CLI coding session and implement the current build task.

User request:
{{requirement_brief}}

Current task:
{{current_task}}

Active TODO scope:
{{current_task_todo}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Retry feedback for this task, if any:
{{current_task_failure_feedback}}

Validation script, if provided:
{{validation_script}}

Do:
- Directly edit real production/project files inside the selected project.
- Implement only the current build task and required dependencies.
- Do not create or modify tests in this step.
- Preserve previous task behavior when editing shared files.
- Do not edit workflow/run files, validation scripts, `.git`, `.qwen`, `.qwen-workflow`, `.ai-workflow`, or files outside the project.
- Do not return tool-call JSON, FILE blocks, code fences, shell scripts, or prompt explanations.

Return a short Markdown summary naming changed production files.
