# Qwen / OpenCode Installation

This project is a Python/FastAPI workflow runner. AI work is executed by an external agent CLI. The two common options are Qwen Code and OpenCode.

## Qwen Code

### Requirements

- Node.js 22 or newer
- npm or Homebrew
- A reachable model provider and API key

### Install

Standalone installer:

```bash
# Linux / macOS
curl -fsSL https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.sh | bash
```

```powershell
# Windows PowerShell
irm https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.ps1 | iex
```

NPM option:

```bash
npm install -g @qwen-code/qwen-code@latest
```

macOS / Linux Homebrew option:

```bash
brew install qwen-code
```

Verify and authenticate:

```bash
qwen --version
qwen --help
qwen
# inside Qwen Code: /auth
```

Windows PATH check:

```powershell
npm config get prefix
where qwen
```

### Configure this project

```powershell
$env:QWEN_BIN="qwen.cmd"
$env:QWEN_TIMEOUT_SEC="1200"
$env:QWEN_USE_SERVE="0"
```

Use mock mode for local UI / workflow testing without a real model call:

```powershell
$env:QWEN_MOCK="1"
```

## OpenCode

### Requirements

- Node.js available in PATH
- OpenCode installed globally or available as a project command
- A configured provider / API key

### Install

Install script:

```bash
curl -fsSL https://opencode.ai/install | bash
```

NPM option:

```bash
npm install -g opencode-ai
```

macOS / Linux Homebrew option:

```bash
brew install anomalyco/tap/opencode
```

Verify and authenticate:

```bash
opencode --help
opencode
# inside OpenCode: /connect
```

### Configure this project

```powershell
$env:OPENCODE_BIN="opencode.cmd"
$env:OPENCODE_TIMEOUT_SEC="1200"
```

## Workflow slash commands

Installing Qwen Code or OpenCode is not enough to make `/wf` and `/wstep` appear in the agent TUI. Those commands are project-specific custom slash commands that must be installed separately.

Install command templates into the current project:

```bash
python scripts/install_agent_commands.py --target all --scope project
```

Then start the agent CLI from this repository root and type `/` to confirm `/wf` and `/wstep` are available.

See `doc/en/AGENT_SLASH_COMMANDS.md` for details and examples.

## Notes

- Keep the CLI executable in PATH before starting uvicorn.
- Prefer one provider per workflow run for predictable logs and artifacts.
- If your company uses proxy or private npm registry settings, configure those before installing the CLIs.
