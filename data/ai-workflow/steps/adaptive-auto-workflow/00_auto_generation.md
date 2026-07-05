Implement the approved task plan for the current task only.

Critical execution contract:
- Modify project files directly only when the CLI actually writes files in this non-interactive run.
- Keep edits inside the selected Project Path only.
- Do not edit `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.
- Do not create workflow artifacts such as `auto_generation*.md`, `task-output.md`, run logs, or workspace notes as the task result.
- Create the actual user-requested product/source/config/test files. For an empty code project, create real source files in the project root or a conventional source folder for the detected language.
- For programming tasks, prose documentation alone is not an implementation. Create or update runnable source files for the requested language and behavior.
- Build owns production/project artifacts only. Do not create or modify tests in this step.
- Test files, if needed by this adaptive task, must be under `tests/` as `tests/test_*.py` or `tests/conftest.py`.
- If direct editing is unavailable, uncertain, or would be returned as tool-call JSON such as `{"name": "edit_file"}`, output complete project file blocks using `FILE: path`, `CONTENT:`, and `END_FILE`.
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

Architecture contract, hard constraint for this Adaptive task:
{{architecture_contract}}

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
6. Preserve the existing project architecture: reuse the responsible module/service/renderer/config path instead of creating a parallel one.

Rules:
- Do not ask the user questions. Make reasonable assumptions and record them in the result.
- Do not hard-code sample inputs, validators, or known sample prompts. Implement the requested behavior generally.
- Do not implement workflow runner logic, repair helper functions, placeholder generators, or simulated task-output helpers unless the user specifically requested those as the product.
- Do not modify validation scripts unless the user explicitly asks to modify that script.
- Do not copy assertions from a validation script into production code just to pass the gate.
- Keep all writes inside the selected Project path.
- Do not write `.git`, `.ai-workflow`, `.qwen-workflow`, absolute paths, or parent-directory paths.
- Do not run git commands.
- Before editing, identify the existing module, service, renderer, config loader, or extension point that owns the behavior. Modify that existing path first.
- Do not create duplicate workflow runners, chat handlers, frontend state stores, service layers, validators, config loaders, or unrelated top-level folders.
- New files are allowed only when they fit the existing architecture and cannot be represented as a small extension of an existing module.
- If generating Python, production modules must be import-safe: no top-level demo prints, no top-level asserts, and no test code in production files.
- If generating Python tests, write them under `tests/`; do not place `test_*.py` at the project root.
- If generating Python tests, match the actual public API behavior in the production files. If a callable mutates its input and returns `None`, assert the mutated input; if it returns a value, assert the returned value. Do not force one style unless the requirement explicitly requires it.
- When a Python callable API contract is unclear, test through a small helper that accepts either a returned result or an in-place mutation, then compares the observed result with the expected behavior.
- If failure feedback mentions side effects, mutation, idempotence, determinism, formatting, paths, imports, or exact output, fix the implementation behavior or test wiring directly; do not weaken, bypass, duplicate, or embed the validation logic.

Completion response:
- Output artifact content only.
- Include a short Markdown summary first.
- If direct edit/write tools were unavailable, uncertain, or would emit tool-call JSON, then output every created or modified file as complete `FILE/CONTENT/END_FILE` blocks.
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

## Architecture Delta Summary
- Existing owner module or extension point reused:
- Why the change fits the current architecture:
- New files/folders introduced, if any, and why they are necessary:
- Architecture drift risk: low | medium | high

Fallback file block format, when direct edit/write tools were unavailable, uncertain, or would emit tool-call JSON:

FILE: relative/path/to/file.py
CONTENT:
complete file content
END_FILE

FILE: tests/test_example.py
CONTENT:
complete pytest content
END_FILE
