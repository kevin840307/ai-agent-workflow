# Qwen Workflow Web

FastAPI + static frontend workflow runner. It provides a ChatGPT-like project UI, but workflow steps are controlled by Python and executed by agent adapters such as Qwen.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000.

## Modes

- Workflow mode runs a selected workflow against one project path.
- Chat mode sends normal chat prompts to the selected project session.
- Workflow Designer is available at http://127.0.0.1:8000/workflow-designer.

## Qwen Runtime

By default the app tries to use `qwen serve` for lower latency:

```text
POST qwen serve /session/<session>/prompt
```

If no matching server is running, the app starts one for the project workspace. Session behavior:

- Normal workflow/chat calls reuse the project `qwen_session_id`.
- Consensus agent steps can request fresh internal Qwen sessions with `freshSessionPerAgent`.
- Reset Project creates a new Qwen session id without creating a new project.

Useful environment variables:

- `QWEN_BIN`: Qwen executable. Default is `qwen.cmd` on Windows, `qwen` elsewhere.
- `QWEN_USE_SERVE`: set `0` to disable serve API and use CLI fallback path.
- `QWEN_SERVE`: set `0` to prevent auto-starting `qwen serve`.
- `QWEN_SERVE_FALLBACK_CLI`: set `1` to use CLI when serve fails.
- `QWEN_TIMEOUT_SEC`: agent timeout seconds. Default `1200`.
- `QWEN_MOCK`: set `1` for mock output during local UI testing.
- `WORKFLOW_TEST_COMMAND`: command used by the Run Test step. Default `python -m pytest`.

If `qwen -p "hello world"` works in cmd, keep Auth blank/none in the UI so the app uses your existing Qwen settings.

## Workflows

Workflow bundles live under `data/workflows/<workflow-folder>/`.

```text
workflow.json
prompts/
skills/
functions/
```

The built-in workflow is `data/workflows/system-controlled-qwen` and is read-only in the UI. Custom workflows use the same folder format and can edit:

- step type, prompt template, expected files, validator, retry target, retry count, timeout
- interaction mode
- review strategy
- consensus agent settings such as `agentCount`, `agentMaxRetries`, and `freshSessionPerAgent`

Python validation steps do not need to call an agent. Their `validator` field selects a backend function from `/api/workflows/functions`.

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

```powershell
python -m compileall app tests
python -m unittest discover -s tests
```

Optional frontend syntax check:

```powershell
Get-Content -Raw static\js\main.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-runner.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer.js | node --input-type=module --check
```

## Architecture

See `ARCHITECTURE.md` for module responsibilities and extension points.
