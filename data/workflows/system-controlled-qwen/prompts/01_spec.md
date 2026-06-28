You are generating the workflow artifact `output/spec.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not call tools.
Use a deterministic format: no title before the first `##` heading, no extra sections, no timestamps, no conversational text.

If the requirement is clear enough to continue, do not ask questions. For simple coding tasks, make reasonable assumptions and record them in Unknowns or Rules. Ask the user only when a missing decision makes the project impossible to specify.
Ignore previous Qwen session tasks. The Requirement below is the source of truth. Do not reuse older filenames, functions, features, or test plans unless the current Requirement asks for them.

Project Path: {{project_path}}
Workflow Workspace: {{workspace_path}}

Project Overview:
{{project_overview}}

Project Profile:
{{project_profile}}

Architecture:
{{architecture}}

Requirement:
{{requirement}}

User Guidance:
{{guidance}}

Previous Failure Feedback:
{{failure_feedback}}

Write a concise spec with exactly these section headings, in this exact order:

## Goal
- One bullet beginning with the concrete user goal.

## Scope
- Bullet list of what will be implemented.

## Out of Scope
- Bullet list of what will not be implemented.

## Input
- Bullet list of expected inputs and existing project context.

## Output
- Bullet list of expected files, behavior, or artifacts.

## Rules
- Bullet list of implementation constraints. Mention tests must be separate from production code. If Project Profile or Architecture shows an existing project language, framework, or folder structure, require the implementation to extend it instead of creating an unrelated structure.

## Acceptance Criteria
Use stable sequential IDs. Include at least AC-001. Keep IDs stable across retries for the same requirement.
- AC-001: ...
- AC-002: ...

## Unknowns
- List only non-blocking unknowns. If none, write "- None blocking."
