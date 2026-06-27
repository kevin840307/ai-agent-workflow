# Qwen Workflow Web MVP

A small FastAPI web app that runs a Python-controlled AI workflow with Qwen CLI as the agent worker.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000.

## Real Qwen Mode

Install and authenticate Qwen CLI, then run without `QWEN_MOCK=1`. The runner invokes:

```text
qwen.cmd --session-id <web-session-uuid> --chat-recording -p "<prompt>"
```

On Windows, `qwen.cmd` avoids PowerShell execution-policy errors from `qwen.ps1`.
If `qwen -p "hello word"` works in cmd, leave Auth as `none` so the app uses your existing Qwen settings.

## Mock Mode

```powershell
$env:QWEN_MOCK="1"
python -m uvicorn app.main:app --reload --port 8000
```

## Optional Settings

- `QWEN_BIN`: Qwen executable path/name. Default: `qwen.cmd` on Windows, `qwen` elsewhere.
- `QWEN_TIMEOUT_SEC`: Qwen subprocess timeout. Default: `1200`
- `QWEN_REUSE_SESSION`: reuse one Qwen session per Web session. Default: `1`
- `QWEN_BARE`: pass `--bare` to Qwen CLI. Default: `0`
- `QWEN_AUTH_TYPE`: optional environment override for Qwen auth type. If unset, the app uses the Web UI setting stored in `data/settings.json` and defaults to blank/none.
- `WORKFLOW_TEST_COMMAND`: test command run during the test step. Default: `python -m pytest`
