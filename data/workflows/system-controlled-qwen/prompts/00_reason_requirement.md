You are producing a reasoning artifact for this workflow.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Do not output implementation code. Do not output FILE/CONTENT/END_FILE blocks.
Do not modify project files. This step only writes `output/reasoning.md`.

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

Create a concise reasoning artifact that helps later Spec, Todo, Test, and Build steps stay aligned with the current requirement and existing project.

Use exactly these sections, in this exact order:

Status: DONE

## Requirement Understanding
- Summarize the concrete user goal as statements, not questions.

## Existing Project Evidence
- List observed files, language, framework, runtime, tests, and layout evidence from Project Overview / Project Profile / Architecture.

## Implementation Direction
- Explain the recommended direction that fits the existing project.

## Files Likely To Change
- Production files:
- Test files:

## Constraints
- List rules later steps must follow.
- Keep production code and tests owned by separate workflow steps.
- Build must not create or modify tests/ files.

## Assumptions
- List reasonable non-blocking assumptions. If none, write "- None.".

## Risks
- List concrete risks later steps should avoid.
