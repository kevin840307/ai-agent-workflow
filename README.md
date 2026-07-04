# Qwen Workflow Web

Qwen Workflow Web is a local **AI Agent Workflow Runner**. It is not only a chat UI: the user enters a requirement in the browser, while a Python/FastAPI runner controls a fixed workflow and delegates generation work to external agent CLIs such as Qwen Code or OpenCode.

The core idea is:

```text
Agent CLI = generate, edit, review, and explain failures
Python runner = orchestrate, validate, retry, gate, log, and protect workspaces
Web UI = operate projects, workflows, assets, runs, and artifacts
```

## Features

| Feature | Description |
|---|---|
| Chat-style runner | Project-based chat UI for running controlled workflows |
| Workflow Runner | Executes selected workflow steps in order |
| Workflow Designer | Edits workflow steps, prompts, retry policy, review strategy, and validation settings |
| AI Workflow Assets | CRUD UI for prompts, contracts, and Python functions |
| Qwen / OpenCode providers | Uses Qwen Code CLI or OpenCode CLI as the external agent worker |
| Project-local agent guard | Writes `.qwen/settings.json` and `opencode.json` so CLI edit tools stay project-scoped |
| Retry / repair loop | Sends failed validation or review feedback back to the owner step |
| External validation | Runs an optional Python validation script; empty script means skipped PASS |
| Artifacts | Stores run outputs, logs, validation reports, and generated files |
| Workflow metadata protection | `kind: system`, `protected: true`, and `deletable: false` are enforced by UI and API |

## Built-in workflows

### Adaptive Auto Workflow

A simple automatic loop for broad tasks:

```text
User requirement
  -> Step 1: Auto Generation
  -> Step 2: AI Review
  -> Step 3: Run External Validation optional
```

Step 3 uses the shared `run_external_validation` Python function:

- No validation script: skip external validation and return `Status: PASS`.
- Validation script provided: execute the Python script.
- Script failed: write stdout / stderr / exit code to the validation artifact and return the error message to `auto_generation` for repair.

### General Auto Development

A fuller engineering workflow for tasks that need specification, todo planning, build, tests, review, validation, and final gate.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

For the current MVP, run a single uvicorn process. The local locks, run state, and JSON store are designed for single-machine / single-process usage.

## Basic usage

1. Open the runner UI.
2. Create or select a project.
3. Set the project path.
4. Select a workflow, such as `Adaptive Auto Workflow`.
5. Enter a requirement.
6. Optionally provide a Python validation script path, for example:

```text
tools/validate_config.py
```

7. Run the workflow and review the generated artifacts.

Validation scripts may support:

```text
--project <project_path> --workspace <run_workspace> --output <output_dir>
```

If the script does not accept these arguments, the runner falls back to:

```text
python <script>
```

## Agent installation and slash commands

Install Qwen Code / OpenCode first, then install this project's custom `/wf` and `/wstep` command templates if you want to run workflows directly from the agent TUI. Installing the agent CLI alone does not create these project commands.

See:

```text
doc/en/AGENT_INSTALLATION.md
doc/en/AGENT_SLASH_COMMANDS.md
doc/en/AGENT_PROJECT_GUARD.md
doc/zh-TW/AGENT_INSTALLATION.md
doc/zh-TW/AGENT_SLASH_COMMANDS.md
doc/zh-TW/AGENT_PROJECT_GUARD.md
```

Install command templates into the current project:

```bash
python scripts/install_agent_commands.py --target all --scope project
```

This creates project-local commands:

```text
.qwen/commands/wf.md
.qwen/commands/wstep.md
.opencode/commands/wf.md
.opencode/commands/wstep.md
```

Common environment variables:

| Variable | Description |
|---|---|
| `QWEN_BIN` | Qwen CLI path; Windows default is `qwen.cmd` |
| `QWEN_USE_SERVE` | Set `1` to use qwen serve API; default uses CLI |
| `QWEN_TIMEOUT_SEC` | Qwen timeout seconds; default 1200 |
| `QWEN_MOCK` | Set `1` to use the mock agent for local tests |
| `OPENCODE_BIN` | OpenCode CLI path; Windows default is `opencode.cmd` |
| `OPENCODE_TIMEOUT_SEC` | OpenCode timeout seconds; default 1200 |
| `WORKFLOW_TEST_COMMAND` | Test command for test steps; default `python -m pytest` |

## Project-local agent guard

Before Qwen/OpenCode runs, the runner creates or updates project-local guard files:

```text
<project>/.qwen/settings.json
<project>/.qwen/QWEN.md
<project>/opencode.json
```

The intended policy is: unrestricted read context, project-only writes, and dangerous operations denied. Qwen/OpenCode use their own edit/write tools directly. After the agent run, the Python runtime checks which project files changed. The platform no longer materializes platform file blocks for real workflow runs; mock mode may still simulate direct edits for tests.

See `doc/en/AGENT_PROJECT_GUARD.md` or `doc/zh-TW/AGENT_PROJECT_GUARD.md`.

## Asset layout

Global assets:

```text
data/ai-workflow/
  workflows/*.workflow
  contracts/**/*.yaml
  steps/**/*.md
  functions/**/*.py
```

Project-local overrides:

```text
<project>/.ai-workflow/
  workflows/
  contracts/
  steps/
  functions/
```

Resolution order:

```text
1. <project>/.ai-workflow/*
2. data/ai-workflow/*
```

## Tests

Daily checks:

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
```

Manual and opt-in checks are documented in:

```text
doc/en/TESTING.md
doc/zh-TW/TESTING.md
```

## Documentation

English documentation is the default entry path. Traditional Chinese documentation is available beside it.

| Area | English | 中文 |
|---|---|---|
| Documentation index | `doc/en/README.md` | `doc/zh-TW/README.md` |
| Agent installation | `doc/en/AGENT_INSTALLATION.md` | `doc/zh-TW/AGENT_INSTALLATION.md` |
| Agent slash commands | `doc/en/AGENT_SLASH_COMMANDS.md` | `doc/zh-TW/AGENT_SLASH_COMMANDS.md
doc/zh-TW/AGENT_PROJECT_GUARD.md` |
| Adaptive workflow | `doc/en/ADAPTIVE_AUTO_WORKFLOW.md` | `doc/zh-TW/ADAPTIVE_AUTO_WORKFLOW.md` |
| Workflow metadata | `doc/en/WORKFLOW_METADATA.md` | `doc/zh-TW/WORKFLOW_METADATA.md` |
| Frontend structure | `doc/en/FRONTEND_STRUCTURE.md` | `doc/zh-TW/FRONTEND_STRUCTURE.md` |
| Testing | `doc/en/TESTING.md` | `doc/zh-TW/TESTING.md` |

Root-level `doc/*.md` files are kept as compatibility entry points for existing tests and links.

---

# 中文簡介

Qwen Workflow Web 是一個本機 **AI Agent Workflow Runner**。它不是單純聊天工具，而是讓使用者在 Web UI 輸入需求後，由 Python Runner 控制固定流程，再呼叫 Qwen Code / OpenCode 等外部 Agent CLI 逐步產生、驗證、重試與修復。

主要用途：

- 公司內部 AI Agent Web UI
- 可控的 Spec → Todo → Build → Test → Review 流程
- Regression Test Framework 產檔與驗證流程
- 用固定 workflow、retry、validation 補足小模型穩定性
- 將 Qwen / OpenCode CLI 包成可操作、可追蹤、可驗證的 Web 平台

中文文件請從 `doc/zh-TW/README.md` 開始閱讀。
