# Qwen / OpenCode 安裝

本專案是 Python/FastAPI workflow runner。真正執行 AI 任務的是外部 Agent CLI，常見選擇是 Qwen Code 或 OpenCode。

## Qwen Code

### 安裝需求

- Node.js 22 或以上
- npm 或 Homebrew
- 可連線的模型 Provider 與 API Key

### 安裝

Standalone installer：

```bash
# Linux / macOS
curl -fsSL https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.sh | bash
```

```powershell
# Windows PowerShell
irm https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.ps1 | iex
```

NPM：

```bash
npm install -g @qwen-code/qwen-code@latest
```

macOS / Linux 也可用 Homebrew：

```bash
brew install qwen-code
```

確認與登入：

```bash
qwen --version
qwen --help
qwen
# 在 Qwen Code 內執行：/auth
```

Windows PATH 檢查：

```powershell
npm config get prefix
where qwen
```

### 專案設定

```powershell
$env:QWEN_BIN="qwen.cmd"
$env:QWEN_TIMEOUT_SEC="1200"
$env:QWEN_USE_SERVE="0"
```

本機測試如果不想真的呼叫模型，可以用 mock：

```powershell
$env:QWEN_MOCK="1"
```

## OpenCode

### 安裝需求

- Node.js 已加入 PATH
- OpenCode 可用全域指令或專案指令啟動
- 已設定 Provider / API Key

### 安裝

Install script：

```bash
curl -fsSL https://opencode.ai/install | bash
```

NPM：

```bash
npm install -g opencode-ai
```

macOS / Linux Homebrew：

```bash
brew install anomalyco/tap/opencode
```

確認與登入：

```bash
opencode --help
opencode
# 在 OpenCode 內執行：/connect
```

### 專案設定

```powershell
$env:OPENCODE_BIN="opencode.cmd"
$env:OPENCODE_TIMEOUT_SEC="1200"
```

## Workflow slash commands

只安裝 Qwen Code 或 OpenCode 還不會讓 Agent TUI 出現 `/wf` 與 `/wstep`。這兩個是本專案提供的 project-specific custom slash command，需要另外安裝。

安裝 command template 到目前專案：

```bash
python scripts/install_agent_commands.py --target all --scope project
```

接著從本 repository root 啟動 Agent CLI，輸入 `/` 確認可以看到 `/wf` 與 `/wstep`。

詳細說明與範例請看 `doc/zh-TW/AGENT_SLASH_COMMANDS.md`。

## 注意事項

- 啟動 uvicorn 前，先確認 CLI 指令可在同一個 shell 執行。
- 建議同一次 workflow run 使用單一 provider，log 與 artifact 會比較好追蹤。
- 公司環境若需要 proxy 或私有 npm registry，請先設定再安裝 CLI。
