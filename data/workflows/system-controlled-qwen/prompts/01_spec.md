You are generating the workflow artifact `output/spec.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not call tools.

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

Write a concise spec with exactly these section headings:

## Goal
State the user goal.

## Scope
List what will be implemented.

## Out of Scope
List what will not be implemented.

## Input
List expected inputs and existing project context.

## Output
List expected files, behavior, or artifacts.

## Rules
List implementation constraints. Mention tests must be separate from production code. If Project Profile or Architecture shows an existing project language, framework, or folder structure, require the implementation to extend it instead of creating an unrelated structure.

## Acceptance Criteria
Use stable IDs. Include at least AC-001.
- AC-001: ...
- AC-002: ...

## Unknowns
List only non-blocking unknowns. If none, write "- None blocking."
