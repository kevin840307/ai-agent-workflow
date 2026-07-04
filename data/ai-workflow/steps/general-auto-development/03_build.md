Implement the approved task plan for the current task only.

Critical execution contract:
- Use Qwen/OpenCode built-in file edit/write tools to modify project files directly.
- Do not return source code for the platform to materialize.
- Do not output full file contents.
- The platform will only inspect the project diff after you finish.
- Keep edits inside the selected Project Path only.
- Do not edit `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.
- Build owns production/project artifacts only. Do not create or modify tests in this step.

User requirement, kept brief:
{{requirement}}

Current build task:
{{current_task}}

Current task TODO. This is the active scope for this Build call:
{{current_task_todo}}

Task-scoped existing file context. Preserve these contents when modifying the same files:
{{current_task_file_context}}

Project index:
{{project_index}}

Architecture summary:
{{architecture}}

Task-scoped failure feedback only:
{{current_task_failure_feedback}}

Validation script path, if provided:
{{validation_script}}

Validation script content, read-only acceptance criteria:
{{validation_script_content}}

Rules:
- Implement only the current task TODO shown above, plus already-required dependencies. Do not proactively implement future task TODO files.
- If you edit an existing file, preserve previous task behavior; never replace a shared file with only the current task fragment.
- Do not implement workflow runner logic, repair helper functions, placeholder generators, or simulated task-output helpers unless the user specifically requested those as the product.
- If the requirement asks for a reusable tool, script, CLI, or utility, implement a real executable/reusable project artifact.
- If the requirement asks for data, config, or document output, write the requested artifact exactly in the requested format/path.
- Follow the existing architecture, language, source layout, naming style, and dependency style from Project index and Architecture summary.
- Do not hard-code sample inputs, validator internals, or one-off examples as product behavior.
- Existing validation scripts are protected acceptance tools. Never modify them unless the user explicitly asked to modify the validator itself.
- Keep generated edits inside Project path only.
- Do not write `.git`, `.ai-workflow`, `.qwen-workflow`, absolute paths, or parent-directory paths.
- Do not run `git commit`, `git push`, or commands that change repository history or remote state.

Completion response:
- After editing files directly, respond with a brief Markdown summary only.
- Do not include full file contents.
