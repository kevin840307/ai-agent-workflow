# Agent Project Guard

AI Workflow now prepares project-local Qwen/OpenCode guard files before agent execution:

```text
<project>/.qwen/settings.json
<project>/.qwen/QWEN.md
<project>/opencode.json
```

The goal is to let Qwen/OpenCode use their own edit/write tools while keeping writes project-scoped.

## Policy

- Read policy: unrestricted. Agents may read external files when they need context.
- Write policy: project only. Agents may create, edit, delete, or rename files only inside the selected Project Path.
- Dangerous operations are denied or blocked by configuration and prompt guardrails.
- Managed guard files are protected: `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, and `.git/**` must not be modified by the agent.

## Qwen Code

AI Workflow writes `.qwen/settings.json` with `tools.approvalMode = auto-edit`, so Qwen can apply file edits without using YOLO mode. It also writes `.qwen/QWEN.md` with project-local guard rules.

Qwen project settings are loaded from `.qwen/settings.json` when Qwen runs from the project root. Qwen also supports `tools.sandbox`, but this project leaves sandbox off by default because the requested read policy is unrestricted.

## OpenCode

AI Workflow writes `opencode.json` with OpenCode permissions:

- `edit`: allow normal project-relative edits, deny common escape paths and managed guard files.
- `external_directory`: allow, so external reads are possible.
- `bash`: deny by default, with only harmless read/status commands allowed.
- `webfetch`, `websearch`, and `task`: denied.

OpenCode controls file edits with the `edit` permission, and `external_directory` is used when tool calls touch paths outside the current working directory.

## Runtime check

After Build / Generate Tests / Adaptive Auto Generation, AI Workflow compares a project file snapshot before and after the agent run.

If Qwen/OpenCode directly changed valid project files, the runtime accepts those edits and records the changed files as the step artifact. For all real workflow runs, Build / Auto Generation / Generate Tests are direct-edit-only: the platform no longer materializes platform file blocks. Mock mode may still simulate direct edits for automated tests.

This is not an OS sandbox. The CLI config is the first guard; AI Workflow still keeps its own path guard and post-run project diff validation.
