Continue the same CLI coding session and execute the current AI-generated prompt.

{{thinking_guidance}}
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

Do:
- Directly edit real files inside the selected project.
- Keep earlier completed work intact.
- Keep all tasks for the same user request in one coherent product and architecture. Extend the existing owner module from earlier tasks when practical instead of creating a parallel implementation.
- Before creating a new file, inspect the project snapshot and earlier task results for the existing file that owns this behavior.
- Do not write generated source under `output/`, run artifact folders, path fragments copied from absolute paths, or ad-hoc nested roots unless the existing project architecture already uses them.
- Use the minimum sufficient implementation; do not add unrequested public parameters or parallel/duplicate implementations.
- Keep one canonical production implementation and one canonical test layout.
- Add or update tests when the task prompt asks for tests or when needed to prove the change.
- When this is a repair retry, fix only the concrete failure feedback and preserve working code.
- Do not edit workflow/run files, validation scripts, `.git`, `.qwen`, `.qwen-workflow`, `.ai-workflow`, or files outside the project.
- Do not return tool-call JSON, FILE blocks, code fences, shell scripts, or prompt explanations.

Return a short Markdown summary with changed files, tests added/updated, and what was done.
