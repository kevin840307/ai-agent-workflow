Implement the approved task plan for the current task only.

Critical execution contract:
- Use Qwen/OpenCode built-in file edit/write tools to modify project files directly.
- If the CLI environment does not expose file edit/write tools, output complete project file blocks using `FILE: path`, `CONTENT:`, and `END_FILE`.
- The platform will inspect the project diff after you finish or safely materialize explicit FILE blocks when direct tools are unavailable.
- Do not output standalone code fences. Every created or modified file must be represented by a direct edit or by a `FILE/CONTENT/END_FILE` block.
- Keep edits inside the selected Project Path only.
- Do not edit `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.
- Build owns production/project artifacts only. Do not create or modify tests in this step.
- Production files must contain source/data content only. Do not write Markdown fences, retry feedback, prompt text, or explanatory prose into source files.

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
- Do not copy, rename, or recreate validation scripts inside the project.
- If generating Python, every `.py` file must compile, be import-safe, and avoid top-level demo prints, example runs, asserts, or test functions.
- Keep generated edits inside Project path only.
- Do not write `.git`, `.ai-workflow`, `.qwen-workflow`, absolute paths, or parent-directory paths.
- Do not run `git commit`, `git push`, or commands that change repository history or remote state.

Completion response:
- Do not summarize, restate, or explain the prompt, architecture, rules, or retry feedback.
- Do not respond with only a plan or status.
- If you used direct edit/write tools successfully, respond with a brief Markdown summary that names the changed production files.
- If direct edit/write tools are unavailable or uncertain, output only complete `FILE/CONTENT/END_FILE` blocks for every created or modified production file.
- Do not include extra code fences, shell commands, project profiles, retry feedback, or explanations after the file blocks.
- A FILE block must use this exact shape:
  `FILE: relative/path.ext`
  `CONTENT:`
  full file content
  `END_FILE`
- In file block fallback, the `FILE:` line must contain only a relative file path. Never put `CONTENT`, markdown, bullets, comments, or code on the `FILE:` line.
