You are preparing a project for an automated development workflow.

Requirement:
{{requirement}}

Project path:
{{project_path}}

Detected project profile:
{{project_profile}}

Visible project files:
{{project_overview}}

Read the current project structure before planning any implementation.

Required checks:
- If the project is not empty, infer the existing language, framework, source layout, test layout, and naming style from the files.
- Check whether project-local agent settings exist:
  - `.qwen/settings.json`
  - `opencode.json`
- Treat those settings as project-local runtime context only. Do not copy them to global settings.
- Read files anywhere when needed for understanding, but all future edits must stay inside Project path.
- If `architecture.md` already exists, update it only when it is incomplete or stale.
- If `architecture.md` does not exist, create it in the project root.

If a blocking detail is truly missing, ask one concise question. Ask only when the workflow cannot safely continue.

Output only FILE/CONTENT/END_FILE blocks.

Required file:

FILE: architecture.md
CONTENT:
# Architecture

## Project Summary
- Current purpose:
- User request:

## Runtime Agent Settings
- Qwen project settings: present/missing at `.qwen/settings.json`
- OpenCode project settings: present/missing at `opencode.json`
- Rule: agent read access may use project settings, but generated edits must remain inside the selected Project path.

## Detected Stack
- Primary language:
- Framework/runtime:
- Test framework:
- Package/build command:

## Current Structure
- Source layout:
- Test layout:
- Important config files:

## Implementation Rules
- Follow the existing language and structure.
- Keep changes small and easy to review.
- Keep production code and tests separate.
- Do not edit files outside the selected Project path.
- Do not skip the external validation script.

END_FILE
