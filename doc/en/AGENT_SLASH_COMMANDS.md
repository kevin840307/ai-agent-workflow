# Agent Slash Commands: `/wf` and `/wstep`

Installing Qwen Code or OpenCode only installs the agent CLI itself. It does **not** automatically create this project's workflow commands.

This project provides custom slash-command templates so the agent TUI can call the same Python workflow runner used by the Web UI:

```text
/wf workflow-id "requirement"
/wstep skill.md contract.yaml "requirement"
/wstep /agent-command contract.yaml "requirement"
```

## What these commands do

| Command | Purpose | Backend call |
|---|---|---|
| `/wf` | Run a saved `.workflow` by workflow id | `<pinned Python> scripts/aiwf_agent_command.py /wf ... --wait` |
| `/wstep` | Run one ad-hoc step from a skill/slash command plus contract | `<pinned Python> scripts/aiwf_agent_command.py /wstep ... --wait` |

The command is only a thin entry point. The real execution still happens in Python/FastAPI workflow code, so retry, validation, artifact output, and workspace protection stay consistent with the Web UI.

## Install command templates

Install both Qwen Code and OpenCode command templates into the current project. The installer renders absolute paths to the current Python and stable launcher, then executes non-mutating `/wf` and `/wstep` dry-runs from the target project:

```bash
python scripts/install_agent_commands.py --target all --scope project
```

This creates:

```text
.qwen/commands/wf.md
.qwen/commands/wstep.md
.opencode/commands/wf.md
.opencode/commands/wstep.md
```

Install only one target:

```bash
python scripts/install_agent_commands.py --target qwen --scope project
python scripts/install_agent_commands.py --target opencode --scope project
```

Install globally for the current user:

```bash
python scripts/install_agent_commands.py --target qwen --scope user
python scripts/install_agent_commands.py --target opencode --scope user
```

Global locations:

```text
Qwen Code: ~/.qwen/commands/
OpenCode: ~/.config/opencode/commands/
```

## Verify

A successful install prints `aiwf.agent-command-verification.v1`, proving routing, arguments, and cross-directory controller loading.

Qwen Code:

```bash
qwen
# type / and check /wf and /wstep
```

OpenCode:

```bash
opencode
# type / and check /wf and /wstep
```

## Example usage

Run a saved workflow:

```text
/wf adaptive-auto-workflow "Create a config validation tool"
/wf general-auto-development "Implement config CRUD and tests"
```

Run one ad-hoc step from a markdown skill and contract:

```text
/wstep steps/general-auto-development/03_build.md contracts/general-auto-development/build.yaml "Implement config CRUD"
```

Run one ad-hoc step by delegating to an agent slash command and contract:

```text
/wstep /build contracts/general-auto-development/build.yaml "Implement config CRUD"
```

## Important behavior

- The slash commands execute a shell command from inside the agent CLI.
- Qwen Code supports project commands under `.qwen/commands/` and user commands under `~/.qwen/commands/`; project commands have higher priority.
- OpenCode supports project commands under `.opencode/commands/` and global commands under `~/.config/opencode/commands/`.
- After installation, Qwen/OpenCode can be started from any target project; the generated command uses the absolute stable launcher.
- The Python/virtual environment used during installation must remain available. Reinstall the commands after moving the controller or rebuilding the venv.
- Quote requirements that contain spaces.
- Do not install these commands globally unless you want every project to see `/wf` and `/wstep`.
- Shell execution may require confirmation inside the agent CLI. This is expected.

## Troubleshooting

| Problem | Check |
|---|---|
| `/wf` does not appear | Confirm the command file was copied to `.qwen/commands/` or `.opencode/commands/`, then restart the agent CLI. |
| `ModuleNotFoundError: app` | The installed command is stale or the controller/venv moved. Re-run `install_agent_commands.py` instead of retaining the old command. |
| `python` is not found | Activate `.venv`, or use a shell where Python is already in PATH. |
| Workflow starts but never finishes | Use `--wait` only when you want the agent session to wait for workflow completion; long workflows may take time. |
| OpenCode uses a custom config dir | Pass `--destination <dir>/commands` or set `OPENCODE_CONFIG_DIR` according to your environment. |
