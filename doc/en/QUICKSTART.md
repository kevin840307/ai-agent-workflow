# Quick Start

## 1. Requirements

- Python 3.10 or later
- Qwen Code and/or OpenCode
- A writable project directory
- A local model endpoint when required by the selected CLI

## 2. Start the controller

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000`. Use one uvicorn worker. Different projects/sessions may share configured provider slots, while each project keeps one active writer.

## 3. Run Setup Smoke

The isolated smoke test checks controller access, CLI availability, model response, fresh sessions, and real Agent tool-write behavior. Its capability result is saved outside the project and can only make later task/prompt limits more conservative.

## 4. Simple Mode: first unattended run

1. Select the Project Path.
2. Confirm the model status shows online, or click it to recheck.
3. Enter one concrete requirement.
4. Start the run.

Simple Mode automatically:

```text
inspects the project → creates/reuses a Validation Profile → establishes baseline
→ lets Qwen/OpenCode edit in the effective Project Path cwd
→ validates and repairs → recovers sessions/processes → atomically delivers
```

The main screen keeps only **Overview** and **Validation**. Overview shows the change summary and opens the near-fullscreen Patch Review workbench; Validation shows executed commands, exit codes, duration, required/blocking state, baseline, and related Evidence. Open **Technical Diagnostics** only for raw Agent output, complete logs, Execution Artifacts, Repair Strategy, checkpoints, process/session details, Delivery/Rollback evidence, or retry history.

## 5. Project Validation Profile

On first use, the platform detects existing build/test/lint/type-check commands and saves a Draft profile in controller data, not in the user project. Select **Project Validation** to review and verify it. Successful verification makes it `Verified`; three successful verifications make it `Trusted`. Changes to build/test descriptors mark it `Stale` and require re-verification.

## 6. Advanced Mode

Enable Advanced Mode to choose workflow/profile/thinking, change unattended behavior, edit the Project Validation Profile, configure a project-relative immutable Validation Script, inspect sessions, or use Review Patch.

Qwen/OpenCode always starts with the effective project workspace as cwd. Normal direct runs use the selected Project Path. Isolated unattended runs use a verified copy that preserves project-local `.qwen/settings.json`, `.qwen/QWEN.md`, `opencode.json`, and related configuration.

## 7. Optional `/wf` and `/wstep`

```powershell
python scripts/install_agent_commands.py --target all --scope project
```

The commands use the same workflow kernel as the Web UI.

## Important environment variables

| Variable | Purpose |
|---|---|
| `QWEN_BIN` / `OPENCODE_BIN` | CLI executable path |
| `QWEN_TIMEOUT_SEC` / `OPENCODE_TIMEOUT_SEC` | total Agent attempt timeout |
| `AIWF_AGENT_STALL_TIMEOUT_SEC` | no-output stall timeout; default 300 seconds |
| `AIWF_AGENT_HEARTBEAT_SEC` | heartbeat interval; default 60 seconds |
| `AIWF_AGENT_MAX_CONCURRENCY` | default provider slots; default 2 |
| `AIWF_QWEN_MAX_CONCURRENCY` | Qwen-specific slot override |
| `AIWF_OPENCODE_MAX_CONCURRENCY` | OpenCode-specific slot override |
| `AIWF_VALIDATOR_MAX_CONCURRENCY` | validation process slots |
| `QWEN_MOCK` / `OPENCODE_MOCK` | deterministic test providers only |
