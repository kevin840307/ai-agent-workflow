# Qwen / OpenCode Installation

本專案本身是 Python / FastAPI Runner，真正執行 AI 任務的是外部 Agent CLI。常見選擇是 Qwen Code 或 OpenCode。

> 建議先確認公司環境可連線到對應模型 Provider，並確認 API Key / Proxy / npm registry 設定。

## 1. Qwen Code

### 安裝需求

- Node.js 22 或以上
- npm 或 Homebrew
- 可用的 Qwen / ModelStudio / OpenAI compatible API key

### 安裝

Windows / Linux / macOS 通用 npm 方式：

```bash
npm install -g @qwen-code/qwen-code@latest
```

macOS / Linux 也可用 Homebrew：

```bash
brew install qwen-code
```

確認：

```bash
qwen --version
qwen --help
```

Windows 如果指令找不到，通常要確認 npm global bin 是否在 PATH：

```powershell
npm config get prefix
where qwen
```

### 本專案設定

```powershell
$env:QWEN_BIN="qwen.cmd"
$env:QWEN_TIMEOUT_SEC="1200"
```

Linux / macOS：

```bash
export QWEN_BIN=qwen
export QWEN_TIMEOUT_SEC=1200
```

如果要用 mock agent 做本機功能測試：

```powershell
$env:QWEN_MOCK="1"
```

## 2. OpenCode

### 安裝方式

OpenCode 可用官方下載頁、安裝腳本、npm / package manager 等方式安裝。若公司環境允許 npm，可先用 npm 安裝：

```bash
npm install -g opencode-ai
```

若使用官方 shell installer，請依公司資安規範審查後再執行：

```bash
curl -fsSL https://opencode.ai/install | bash
```

確認：

```bash
opencode --version
opencode --help
```

### 登入 / 設定 Provider

```bash
opencode auth login
```

也可以透過環境變數或專案 `.env` 提供 Provider API key。實際欄位依使用的 Provider 而定。

### 本專案設定

Windows：

```powershell
$env:OPENCODE_BIN="opencode.cmd"
$env:OPENCODE_TIMEOUT_SEC="1200"
```

Linux / macOS：

```bash
export OPENCODE_BIN=opencode
export OPENCODE_TIMEOUT_SEC=1200
```

## 3. 如何選擇 Agent

在 Workflow Designer 的 Step 裡：

- `agent: qwen`：使用 Qwen CLI
- `agent: opencode`：使用 OpenCode CLI

建議：

| 情境 | 建議 |
|---|---|
| 公司已經有 Qwen / Qwen compatible model | 先用 Qwen |
| 想測多 Provider / Copilot / OpenAI compatible | 可試 OpenCode |
| 本機只測 UI / workflow / retry | 用 `QWEN_MOCK=1` |

## 4. 常見問題

### UI 可以開，但 Agent 沒反應

檢查：

```bash
qwen --version
opencode --version
```

再確認環境變數：

```powershell
$env:QWEN_BIN
$env:OPENCODE_BIN
```

### Windows 找不到 qwen.cmd / opencode.cmd

確認 npm global bin 是否在 PATH：

```powershell
npm config get prefix
where qwen
where opencode
```

### 公司網路不能 npm install

建議改用公司內部 npm registry / proxy，或由平台管理者預先安裝 CLI，再透過 `QWEN_BIN` / `OPENCODE_BIN` 指到固定路徑。
