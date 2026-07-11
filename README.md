# Qwen Workflow Web

Agent Workflow Web is a local **AI Agent Workflow Runner**. It is not only a chat UI: the user enters a requirement in the browser, while a Python/FastAPI runner controls a fixed workflow and delegates generation work to external agent CLIs such as Qwen Code or OpenCode.

The core idea is:

```text
Agent CLI = generate, edit, review, and explain failures
Python runner = forward concise prompts, orchestrate steps, validate, retry, gate, log, and protect project-scoped run data
Web UI = operate projects, workflows, assets, runs, and artifacts
```

## Features

| Feature | Description |
|---|---|
| Run Center | User-facing Overview / Changes / Validation instead of raw technical tabs |
| Unified workflow kernel | General and Adaptive share state, session, workspace, retry, validation, and evidence services |
| Checkpoint recovery | Restarts interrupted runs from the latest successful step |
| Role-scoped sessions | Planning, build, validation, and review sessions have separate resume/fresh policies |
| Project lock and path guard | One write run per project; all agent writes remain project-scoped |
| Filesystem-first acceptance | Actual diff and deterministic validation decide whether an agent attempt succeeded |
| Typed recovery | Session, context, timeout, test, path, review, and layout failures use explicit strategies |
| Compact artifacts | Normal users see essential results; verbose diagnostics are packed into one archive |
| SQLite evidence store | WAL-backed normalized projections for runs, steps, tasks, events, sessions, validation, changes, checkpoints, and locks |
| Setup and recommendations | Seven readiness checks plus compact, dismissible workflow/agent/profile/time recommendations |
| Workflow Designer | Simple / Advanced / JSON modes, versioning, import/export, validation, and protection |
| AI Workflow Assets | CRUD UI for prompts, contracts, Python functions, and reusable metadata |
| Risk, approval, and scope control | Low-risk automation, high-risk isolated Patch approval, scope-delta evidence |
| Context handoff and task checkpoints | Fresh-session recovery without replaying completed work |
| Validator plugins | Python, Java, .NET, Node, YAML/XML, SQL, Docker, Kubernetes, and custom commands |
| Product benchmarks | Ten fixed reliability and recovery scenarios with versioned results |
| Qwen / OpenCode providers | Capability-aware adapters with normalized session/context/tool errors |

## UI overview

### Workflow runner

The runner is the main operating screen. Select a project, enter a requirement, optionally open the compact recommendation chip, and run. Environment advice and completion results are dismissible, non-blocking notices. The Run Center keeps the normal experience focused on the current action, readable file changes, and validation evidence. Console, raw logs, full Patch controls, repair policy, all artifacts, and health data are available only from the lazy-loaded Technical Diagnostics drawer.

![Workflow runner](docs/images/ui-workflow-runner.png)

### Workflow designer

The designer manages workflow structure, step contracts, prompt templates, retry settings, review strategy, Python functions, and CLI command examples.

![Workflow designer](docs/images/ui-workflow-designer.png)

### AI workflow assets

The asset manager edits global or project-local workflow assets: prompts, contracts, functions, and workflow metadata.

![AI workflow assets](docs/images/ui-ai-workflow-assets.png)

## Built-in workflows

### Adaptive Auto Workflow

A three-step controller flow for broad tasks:

```text
User requirement
  -> Step 1: AI generates short CLI task prompts
  -> Step 2: Qwen/OpenCode executes those prompts and directly edits project files
  -> Step 3: AI reviews the result, then Python runs validation/test gates when configured
```

Failures are classified before recovery. Deterministic repairs stay in the current validation layer; implementation failures return to the owning task; only actual planning/spec conflicts trigger replanning. The controller does not generate production code or materialize agent edit/write JSON.

### General Auto Development

A fixed development SOP: plan tasks, execute only the owning task, generate tests, run deterministic validation, perform read-only review, execute the immutable user validation contract when configured, and complete only after the atomic Completion Gate passes.

### Security Vulnerability Scan

A read-mostly security workflow that inventories the project, runs supported dependency/static checks, normalizes findings, and produces a security report without exposing arbitrary custom workflows in the product catalog.

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

Run a single uvicorn process (`--workers 1`). Project locks, controller tasks, agent processes, and local SQLite state are designed for a single-machine controller. SQLite is the default store and uses WAL, migrations, normalized projections, and backup support.

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

7. Run the workflow and review Overview, Changes, and Validation. Open Technical Diagnostics only when deeper troubleshooting is needed.

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

The installer pins the current Python and stable launcher, then verifies `/wf` and `/wstep` from the target project. This creates project-local commands:

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
python -m compileall -q app tests
python scripts/validate_workflow_assets.py
python scripts/run_tests.py --mode all --isolate-all
```

The complete matrix is executed in isolated pytest processes because long-running TestClient/workflow fixtures intentionally own background tasks and subprocesses. Real Qwen CLI and Playwright checks are opt-in.

Manual and opt-in checks are documented in:

```text
doc/en/TESTING.md
doc/zh-TW/TESTING.md
```

## Documentation

English documentation is the default entry path. Traditional Chinese documentation is available beside it.

| Area | English | Traditional Chinese |
|---|---|---|
| Documentation index | `doc/en/README.md` | `doc/zh-TW/README.md` |
| Agent installation | `doc/en/AGENT_INSTALLATION.md` | `doc/zh-TW/AGENT_INSTALLATION.md` |
| Agent slash commands | `doc/en/AGENT_SLASH_COMMANDS.md` | `doc/zh-TW/AGENT_SLASH_COMMANDS.md` |
| Agent project guard | `doc/en/AGENT_PROJECT_GUARD.md` | `doc/zh-TW/AGENT_PROJECT_GUARD.md` |
| Adaptive workflow | `doc/en/ADAPTIVE_AUTO_WORKFLOW.md` | `doc/zh-TW/ADAPTIVE_AUTO_WORKFLOW.md` |
| Workflow metadata | `doc/en/WORKFLOW_METADATA.md` | `doc/zh-TW/WORKFLOW_METADATA.md` |
| Frontend structure | `doc/en/FRONTEND_STRUCTURE.md` | `doc/zh-TW/FRONTEND_STRUCTURE.md` |
| Testing | `doc/en/TESTING.md` | `doc/zh-TW/TESTING.md` |
| Stability V11 | `doc/en/STABILITY_V11.md` | `doc/zh-TW/STABILITY_V11.md` |
| Production Readiness V10 | `doc/en/PRODUCTION_READINESS_V10.md` | `doc/zh-TW/PRODUCTION_READINESS_V10.md` |
| System Productization V9 | `doc/en/SYSTEM_PRODUCTIZATION_V9.md` | `doc/zh-TW/SYSTEM_PRODUCTIZATION_V9.md` |
| System Optimization V8 | `doc/en/SYSTEM_OPTIMIZATION_V8.md` | `doc/zh-TW/SYSTEM_OPTIMIZATION_V8.md` |
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


See also: `doc/WORKFLOW_STABILITY_PLAN.md` for the stability score, failure-injection matrix, and isolated-workspace guard pattern.

Latest stability release: `doc/en/STABILITY_V11.md` and `doc/zh-TW/STABILITY_V11.md` document retry object consistency, existing-project pytest ownership, recovery/change UI cleanup, and verified Qwen/OpenCode interactive `/wf` and `/wstep` routing. V10 remains the production validation/completion foundation.
## Local real Qwen cases

Run one-line Prompt cases against the actual Qwen/OpenCode CLI and verify the final project with a required validation script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 -Case all -Agent qwen
```

See `doc/zh-TW/LOCAL_REAL_QWEN_CASES.md`.

