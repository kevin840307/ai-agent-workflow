# Qwen Workflow Web

FastAPI + static frontend workflow runner. It provides a ChatGPT-like project UI, but workflow steps are controlled by Python and executed by agent adapters such as Qwen.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000.

Run this MVP as a single process. Do not start uvicorn with more than one worker; the runtime keeps in-process chat, workflow, and cancellation locks for local single-machine use. `WEB_CONCURRENCY` or `UVICORN_WORKERS` must be unset or set to `1`.

## Modes

- Workflow mode runs a selected workflow against one project path.
- Chat mode sends normal chat prompts to the selected project session.
- Workflow Designer is available at http://127.0.0.1:8000/workflow-designer.

## Qwen Runtime

By default the app uses the Qwen CLI path, because it matches normal `qwen -p "..."` behavior and avoids starting a background server unexpectedly. OpenCode is also supported as an agent provider.

```text
qwen <session/options> <prompt via stdin>
```

`qwen serve` is opt-in. Set `QWEN_USE_SERVE=1` when you want the app to call the serve API:

```text
POST qwen serve /session/<session>/prompt
```

When serve mode is enabled and no matching server is running, the app can start one for the project workspace. Session behavior:

- Normal workflow/chat calls reuse the project `qwen_session_id`.
- Consensus agent steps can request fresh internal Qwen sessions with `freshSessionPerAgent`.
- Reset Project creates a new Qwen session id without creating a new project.

Useful environment variables:

- `QWEN_BIN`: Qwen executable. Default is `qwen.cmd` on Windows, `qwen` elsewhere.
- `QWEN_USE_SERVE`: set `1` to enable Qwen serve API. Default: `0`.
- `QWEN_SERVE`: set `0` to prevent auto-starting `qwen serve`.
- `QWEN_SERVE_FALLBACK_CLI`: set `1` to use CLI when serve fails.
- `QWEN_TIMEOUT_SEC`: agent timeout seconds. Default `1200`.
- `QWEN_MOCK`: set `1` for mock output during local UI testing.
- `WORKFLOW_TEST_COMMAND`: command used by the Run Test step. Default `python -m pytest`.

If `qwen -p "hello world"` works in cmd, keep Auth blank/none in the UI so the app uses your existing Qwen settings.

## OpenCode

OpenCode can be selected from the settings menu as the default agent, or per workflow step by setting Agent Provider to `opencode`.

On Windows the app prefers `opencode.cmd` to avoid PowerShell `.ps1` execution-policy errors. Supported OpenCode modes:

- `run`: invokes `opencode run --session <project-session> <prompt>`
- `prompt_flag`: invokes `opencode --prompt <prompt> --session <project-session>`

The default agent is stored under `agents.default` in `data/settings.json`. Provider settings are stored under `agents.providers`.
Project sessions store provider ids in `agent_session_ids`, so Qwen and OpenCode can both reuse the selected project session. The runner Settings `Reuse` switch is shared by Qwen and OpenCode.
In Chat mode, reused agent sessions receive only the latest user message; workflow prompts and prior chat history are not re-sent because the CLI session owns that context.
OpenCode supports the same baseline runtime controls as Qwen where the CLI allows it: session reuse, timeout, mock mode for local tests, command preview, health status, model, and agent.
If an OpenCode reused session is no longer known by the CLI, the adapter retries once without `--session` and clears that provider session id for the project.
On Windows, if the active FastAPI event loop cannot create asyncio subprocesses, the agent runner automatically falls back to a threaded subprocess call instead of returning a 500.

Useful OpenCode environment variables:

- `OPENCODE_BIN`: OpenCode executable. Default is `opencode.cmd` on Windows, `opencode` elsewhere.
- `OPENCODE_REUSE_SESSION`: set `0` to disable `--session`.
- `OPENCODE_TIMEOUT_SEC`: agent timeout seconds. Default `1200`.
- `OPENCODE_MOCK`: set `1` for mock output during local UI testing.
- `OPENCODE_MODEL`: optional model override.
- `OPENCODE_AGENT`: optional agent override.

## Workflows

Workflow assets live under one canonical root: `data/ai-workflow/`.

```text
data/ai-workflow/
  workflows/*.workflow        # workflow order/include manifest
  steps/**/*.md               # skill / prompt markdown
  contracts/**/*.yaml         # step metadata
  validators/**/*.py          # Python validators
  tools/**/*.py               # Python tools
```

The built-in workflow is `data/ai-workflow/workflows/system-controlled-qwen.workflow` and is read-only in the UI. Custom workflows use the same separated asset format and can edit:

- step type, prompt template, expected files, validator, retry target, retry count, timeout
- interaction mode
- review strategy
- consensus agent settings such as `agentCount`, `agentMaxRetries`, and `freshSessionPerAgent`

Python validation steps do not need to call an agent. Their `validator` field selects a backend function from `/api/workflows/functions`.

Runtime safety:

- The JSON store, settings, prompt templates, workflow configs, and workflow artifacts are written atomically with temp-file replace.
- One chat request can generate in a session at a time. Duplicate chat sends can pass `clientRequestId` for idempotency.
- One workflow run can be active for a project path at a time, even after refresh.
- Startup marks interrupted runs when the previous app process exited mid-run.
- Run logs are rotated in place to keep the latest entries.

Operational endpoints:

- `GET /health`: process liveness.
- `GET /ready`: store/workspace/static readiness checks.
- `GET /metrics`: lightweight in-process counters, timings, and active run count.
- `POST /api/maintenance/cleanup?keep_per_project=20`: removes old inactive run workspaces beyond the retention count.

## Security Scan

The security scan workflow uses a compact consensus design:

1. collect security manifest
2. run a generic consensus agent step internally
3. combine findings
4. generate report
5. validate report
6. finalize report

The visible workflow stays short, while `consensus_agent` can run multiple internal Qwen sessions with per-agent validation and retry.

## Test

Daily checks:

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

Manual opt-in checks are documented in `TESTING.md`, including:

- `RUN_REAL_QWEN=1` minimal real Qwen CLI smoke
- `RUN_REAL_QWEN_FULL=1` full real Qwen system workflow smoke
- `RUN_REAL_QWEN_STABILITY=1` same-prompt stability check
- `RUN_CLEAN_REPO_SMOKE=1` clean repo smoke
- `RUN_PLAYWRIGHT_UI=1` Playwright UI E2E

Optional frontend syntax check:

```powershell
Get-Content -Raw static\js\main.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-runner.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\controller.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\layout-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\step-settings-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\template-editor.js | node --input-type=module --check
```

## Architecture

See `ARCHITECTURE.md` for module responsibilities and extension points.
