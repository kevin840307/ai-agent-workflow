You are preparing project architecture context.

Output only FILE/CONTENT/END_FILE blocks or direct Markdown with `Status: DONE`. Do not output JSON. Do not use code fences. Do not ask questions.

Project Path: {{project_path}}
Workflow Workspace: {{workspace_path}}

Requirement:
{{requirement}}

Project Overview:
{{project_overview}}

Project Profile:
{{project_profile}}

Existing architecture.md:
{{architecture}}

Rules:
- If the project already has files, summarize the current architecture and update architecture.md if needed.
- If architecture.md already exists and is accurate, keep it concise and current.
- Record the detected primary language, framework/runtime, test framework, module layout, entry points, naming conventions, and where production code and tests live.
- If the workflow is adding a second or later feature, preserve the existing architecture and explain how new features should be added consistently.
- Do not write under `.qwen-workflow`.
- Only create or update `architecture.md`.

Return this exact file block:

FILE: architecture.md
CONTENT:
# Architecture

## Overview

## Project Structure

## Runtime And Entry Points

## Data Flow

## Testing Strategy

## Conventions

## Unknowns

## Update Notes
END_FILE
