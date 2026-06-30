# Architecture

## Overview

The app is split into a FastAPI backend, a static frontend, workflow bundle data, and project run workspaces.

```text
app/
  api/routes/               HTTP routes only
  core/                     paths, locks, metrics, API error helpers
  persistence/              JSON store and repositories
  controllers/              compatibility facades for old route imports
  services/                 API use cases and persistence orchestration
  workflow/agents/          provider-neutral agent contracts and providers
  workflow_runtime/          workflow execution, agent calls, prompt building, retry
    agent_adapters/          compatibility facades for old adapter imports
  workflow_functions.py      executable Python workflow functions
  workflow_function_catalog.py
                             function metadata exposed to Workflow Designer
  runtime_modules/           runtime compatibility facade package
static/
  index.html                 runner/chat UI
  workflow-designer.html     workflow configuration UI
data/
  workflows/                 system and custom workflow bundles
  settings.json              local runtime settings
  store.json                 sessions, messages, runs
```

## Request Flow

1. The runner creates or selects a project session.
2. A workflow run is created with a project path and workflow id.
3. `WorkflowExecutor` runs enabled steps in order.
4. `WorkflowActions` resolves each step into an action.
5. Agent steps call `AgentStepRunner`.
6. Python steps call `WorkflowFunctionService`.
7. Artifacts, logs, prompts, answers, guidance, and failure feedback are written under the run workspace.

Project run workspace:

```text
<project>/.qwen-workflow/runs/session-<session-id>/run-<run-id>/
  requirement.md
  input/
  output/
  prompts/
  .workflow/
```

## Agent Layer

Agent support is provider-neutral.

- `AgentManager` resolves a configured provider name.
- `QwenAdapter` prefers Qwen serve and can fall back to CLI when configured.
- `OpenCodeCliAdapter` runs `opencode run --session <project-session> <prompt>` or `opencode --prompt <prompt> --session <project-session>` and is selectable as the default agent or per step provider.
- New agents should implement `AgentClient` in `app/workflow_runtime/agent_adapters/<provider>.py`.
- Provider construction is registered through `ADAPTER_FACTORIES`, keyed by provider `type`.

Recommended extension path for a new agent:

1. Add provider config to `data/settings.json`.
2. Add an adapter implementing `run_stream`, `command_preview`, and `health`.
3. Register its provider type in `ADAPTER_FACTORIES`.
4. Expose UI choices through workflow step `agent` / `provider`.

Chat mode calls `AgentManager.resolve()` without forcing a provider, so it follows `agents.default`. Workflow steps can override that with their `agent` or `provider` field.
Project sessions store provider session ids in `agent_session_ids`; legacy `qwen_session_id` remains for backward compatibility.
Adapters should support the same baseline contract where possible: session reuse, timeout handling, command preview, health metadata, mock mode for local tests, and streamed output callbacks.

## Workflow Bundles

Every workflow should use the same folder format:

```text
data/workflows/<folder>/
  workflow.json
  prompts/*.md
  skills/
  functions/
```

`workflow.json` is the source of truth for:

- step order and enabled state
- step type
- prompt template path
- output filename
- validator function
- retry behavior
- timeout
- human interaction
- expected files
- review and consensus settings

The system workflow is read-only in the UI. Custom workflows are stored in their own folders.

## Prompt Building

`PromptBuilder` loads the step template, fills runtime placeholders, and appends context when the template does not explicitly include it.

Common placeholders:

- `{{requirement}}`
- `{{project_profile}}`
- `{{architecture}}`
- `{{spec}}`
- `{{todo}}`
- `{{test_result}}`
- `{{failure_feedback}}`
- `{{security_context}}`
- `{{security_findings}}`

Prompt copies are saved to `prompts/<step-key>.md` inside each run workspace so the UI can inspect what was sent.

## Retry Model

Retry is workflow-driven.

- `retryFromStepKey` selects where to restart after a failure.
- `maxRetries` is counted on the retry target step.
- `run_test` may classify failure as a test-generation issue or build issue.
- Failure feedback is appended to `input/failure-feedback.md` and injected into retry prompts when enabled.
- Step and run failures include `error_code` so the UI can choose stable actions without parsing English messages.

Manual Retry from the UI resets retry counts from the selected step and resumes from there.

## Stability Guards

- `app/workflow_runtime/error_codes.py` classifies workflow, validation, timeout, agent process, session, expected-file, and project-diff failures.
- `AgentStepRunner` retries once with a fresh agent session when a provider reports a recoverable session problem.
- `WorkflowExecutor` supports `requireProjectChanges` / `projectDiffGate` for steps that must modify the selected project path.
- `app/services/workflow_lint_service.py` validates workflow config before save; `/api/workflows/lint` returns non-throwing lint issues for UI previews.
- `build` steps default `requireProjectChanges` to true when workflow config is normalized.

## Python Functions

Executable functions live in `app/workflow_functions.py` and are registered in `PYTHON_FUNCTIONS`.

UI metadata lives in `app/workflow_function_catalog.py` and is returned by `/api/workflows/functions`.

When adding a new Python workflow function:

1. Implement `def my_function(ctx: WorkflowFunctionContext, artifact: str | None = None)`.
2. Add it to `PYTHON_FUNCTIONS`.
3. Add metadata to `AVAILABLE_WORKFLOW_FUNCTIONS`.
4. Add or update tests if it affects validation, file writes, or retry routing.

## Consensus Agent

`consensus_agent` is a generic Python-controlled agent step. It can run several internal agent attempts while the UI shows one visible step.

Important config:

- `agentCount`
- `agentMaxRetries`
- `candidateValidator`
- `artifactPattern`
- `freshSessionPerAgent`

This is used by the security workflow, but the same concept can support any generate + validate + retry loop.

## Safety Rules

- Artifact API resolves paths and rejects access outside the run workspace.
- Build file blocks cannot escape the selected project path.
- Build step must write production files, not tests.
- Generate Tests owns `tests/`.
- Python validators should fail loudly with actionable messages because those messages are sent back into retry prompts.
