Continue the CLI coding session and complete this task.

User request:
{{requirement_brief}}

Current task:
{{current_task}}

Human prompt to execute:
{{current_task_prompt}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Retry feedback for this task, if any:
{{current_task_failure_feedback}}

Do:
- Directly edit real files inside the selected project.
- Keep earlier completed work intact.
- Add or update tests when the task prompt asks for tests or when needed to prove the change.
- Do not edit workflow/run files, validation scripts, `.git`, `.qwen`, `.qwen-workflow`, `.ai-workflow`, or files outside the project.
- Do not return tool-call JSON, FILE blocks, code fences, shell scripts, or prompt explanations.

Return a short Markdown summary with changed files and what was done.
