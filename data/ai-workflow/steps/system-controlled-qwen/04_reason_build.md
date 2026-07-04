You are producing a build reasoning artifact for this workflow.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Do not output implementation code. Do not output full file contents.
Do not modify project files. This step only writes `output/build-reasoning.md`.
Do not create tests in this step.

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

Requirement Reasoning:
{{reasoning}}

Spec:
{{spec}}

Todo:
{{todo}}

Test Plan:
{{test_plan}}

Previous Failure Feedback:
{{failure_feedback}}

Create a concise implementation reasoning artifact for the Build step.

Use exactly these sections, in this exact order:

Status: DONE

## Target Production Files
- List only production files that Build should create or modify.

## Forbidden Files
- List files or folders Build must not create or modify.
- Include tests/ when tests already belong to Generate Tests.

## Implementation Plan
- Step-by-step production implementation plan.

## Acceptance Criteria Mapping
- Map AC IDs from Spec to production changes.

## Test Awareness
- Summarize what generated tests expect, without writing test code.

## Retry Guidance
- If there is failure feedback, explain what the next Build attempt must fix.
- If there is no failure feedback, write "- None.".
