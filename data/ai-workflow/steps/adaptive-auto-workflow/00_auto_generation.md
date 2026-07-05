Implement the approved task plan for the current task only.

Critical execution contract:
- Prefer the Qwen/OpenCode built-in file edit/write tools to modify project files directly.
- Keep edits inside the selected Project Path only.
- Do not edit `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.
- Build owns production/project artifacts only. Do not create or modify tests in this step.
- Test files, if needed by this adaptive task, must be under `tests/` as `tests/test_*.py` or `tests/conftest.py`.
- If your CLI environment cannot use file edit/write tools, output complete project file blocks using `FILE: path`, `CONTENT:`, and `END_FILE`.
- When falling back to file blocks, every file block must contain complete runnable project content for that file.
- In file block fallback, `FILE:` must contain only a relative file path. Never put `CONTENT`, prose, bullets, or code on the `FILE:` line.
- Do not output standalone code fences. Every created or modified file must be represented by a direct edit or by a `FILE/CONTENT/END_FILE` block.

You are running Adaptive Auto Workflow task execution.

User request:
{{requirement}}

Project path:
{{project_path}}

Current task:
{{current_task}}

Generated task prompt. Treat this as the active scope for this call:
{{current_task_prompt}}

Task TODO, if available:
{{current_task_todo}}

Task-scoped existing file context. Preserve these contents when modifying the same files:
{{current_task_file_context}}

Project index:
{{project_index}}

Architecture summary:
{{architecture}}

Task-scoped failure feedback only:
{{current_task_failure_feedback}}

Latest external validation result, if this run has already checked the partial project:
{{external_validation_result}}

Validation script, if provided:
{{validation_script}}

Validation script content, read-only acceptance criteria:
{{validation_script_content}}

Guidance from the user:
{{guidance}}

Your job:
1. Complete only the current generated task prompt.
2. Output real project direct file edits.
3. Include focused tests when the task is testable because Adaptive Auto Workflow is an all-in-one task loop.
4. Keep production code and tests separated; put pytest tests under `tests/`.
5. Preserve completed earlier task work and do not proactively implement future task prompts unless required as a dependency.

Rules:
- Do not ask the user questions. Make reasonable assumptions and record them in the result.
- Do not hard-code sample inputs, validators, or known sample prompts. Implement the requested behavior generally.
- Do not implement workflow runner logic, repair helper functions, placeholder generators, or simulated task-output helpers unless the user specifically requested those as the product.
- Do not modify validation scripts unless the user explicitly asks to modify that script.
- Do not copy assertions from a validation script into production code just to pass the gate.
- Keep all writes inside the selected Project path.
- Do not write `.git`, `.ai-workflow`, `.qwen-workflow`, absolute paths, or parent-directory paths.
- Do not run git commands.
- If generating Python, production modules must be import-safe: no top-level demo prints, no top-level asserts, and no test code in production files.
- If generating Python tests, write them under `tests/`; do not place `test_*.py` at the project root.
- If failure feedback mentions side effects, mutation, idempotence, determinism, formatting, paths, imports, or exact output, fix the implementation behavior or test wiring directly; do not weaken, bypass, duplicate, or embed the validation logic.

Completion response:
- Output artifact content only.
- Include a short Markdown summary first.
- If direct edit/write tools were unavailable, then output every created or modified file as complete `FILE/CONTENT/END_FILE` blocks.
- At least one direct project edit or file block is required.
- Do not include extra code fences, shell commands, project profiles, retry feedback, or explanations after the file blocks.

Required artifact shape:

# Adaptive Generation Result

Status: READY

## Current Task
- Task ID:
- What changed:

## Files

List the real project files changed.

Fallback file block format, only when direct edit/write tools were unavailable:

FILE: relative/path/to/file.py
CONTENT:
complete file content
END_FILE

FILE: tests/test_example.py
CONTENT:
complete pytest content
END_FILE
