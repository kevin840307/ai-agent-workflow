Continue the CLI coding session and complete this task.

User request:
Create a deterministic Python helper named workflow_greeting and verify it with tests.

Current task:
Task ID: TASK-001
Task Title: Implement feature and tests
Task Index: 1/1
Task Owner Step: build
Task Phase: adaptive_generation
Task TODO File: output/todos/TASK-001.md

Human prompt to execute:
# TASK-001: Implement feature and tests

Status: READY

## AI-Generated Prompt
Create the requested Python helper and focused tests inside the project. Directly edit real project files and keep the code import-safe.

## Acceptance
- Production helper exists
- Tests verify the helper
- Project tests pass


Project snapshot, brief:
Detected project profile:
- Dominant source extensions: .md (1)
- Test framework: unknown
- Marker/config files: none detected
- Source roots by usage: none detected
- Existing source files: none detected
- Existing test files: none detected
- Architecture guidance: extend the dominant existing language, module layout, naming, and test style. Do not introduce a new src/tests layout unless it is the dominant source root or architecture.md says to use it.
# Project Index
## Project Path
- /mnt/data/mock-e2e-controller-logs/projects/adaptive-auto-workflow
## Deterministic Profile
- Dominant source extensions: .md (1)
- Test framework: unknown
- Marker/config files: none detected
- Source roots by usage: none detected
- Existing source files: none detected
- Existing test files: none detected
- Architecture guidance: extend the dominant existing language, module layout, naming, and test style. Do not introduce a new src/tests layout unless it is the dominant source root or architecture.md says to use it.
## Suggested Test Commands
- Unknown; use the configured workflow test command or project convention.
## Workspace Isolation
- Agent writes must stay inside Project Path.
- External paths may be read as context but are not write targets.
- Protected write directories: `.git`, `.ai-workflow`, `.qwen-workflow`
## Visible Files
- README.md

Retry feedback for this task, if any:
No failure feedback for this task yet.

Do:
- Directly edit real files inside the selected project.
- Keep earlier completed work intact.
- Add or update tests when the task prompt asks for tests or when needed to prove the change.
- Do not edit workflow/run files, validation scripts, `.git`, `.qwen`, `.qwen-workflow`, `.ai-workflow`, or files outside the project.
- Do not return tool-call JSON, FILE blocks, code fences, shell scripts, or prompt explanations.

Return a short Markdown summary with changed files and what was done.


Human interaction rule:
    - Do not ask the user questions in this step.
    - Make reasonable assumptions and write them into the artifact when needed.
    - If the step cannot proceed safely, fail with a concrete error in the artifact instead of asking.