# Agent Slash Commands：`/wf` 與 `/wstep`

只安裝 Qwen Code 或 OpenCode，代表只安裝了 Agent CLI 本體，**不會自動擁有本專案的 workflow 指令**。

本專案提供 custom slash-command template，讓 Agent TUI 可以呼叫跟 Web UI 相同的 Python workflow runner：

```text
/wf workflow-id "需求"
/wstep skill.md contract.yaml "需求"
/wstep /agent-command contract.yaml "需求"
```

## 這些指令做什麼

| 指令 | 用途 | 後端實際呼叫 |
|---|---|---|
| `/wf` | 依 workflow id 執行已儲存的 `.workflow` | `python -m app.cli.aiwf /wf ... --wait` |
| `/wstep` | 用 skill/slash command + contract 執行單一步驟 | `python -m app.cli.aiwf /wstep ... --wait` |

這些 slash command 只是薄薄一層入口。真正執行仍然走 Python/FastAPI workflow code，所以 retry、validation、artifact、workspace 保護都會跟 Web UI 保持一致。

## 安裝 command template

安裝 Qwen Code 與 OpenCode 兩種 command template 到目前專案：

```bash
python scripts/install_agent_commands.py --target all --scope project
```

會建立：

```text
.qwen/commands/wf.md
.qwen/commands/wstep.md
.opencode/commands/wf.md
.opencode/commands/wstep.md
```

只安裝其中一種：

```bash
python scripts/install_agent_commands.py --target qwen --scope project
python scripts/install_agent_commands.py --target opencode --scope project
```

安裝到目前使用者全域：

```bash
python scripts/install_agent_commands.py --target qwen --scope user
python scripts/install_agent_commands.py --target opencode --scope user
```

全域位置：

```text
Qwen Code: ~/.qwen/commands/
OpenCode: ~/.config/opencode/commands/
```

## 驗證

Qwen Code：

```bash
qwen
# 輸入 /，確認看得到 /wf 與 /wstep
```

OpenCode：

```bash
opencode
# 輸入 /，確認看得到 /wf 與 /wstep
```

## 使用範例

執行已儲存 workflow：

```text
/wf adaptive-auto-workflow "建立 config 驗證工具"
/wf general-auto-development "實作 config CRUD 與測試"
```

用 markdown skill 與 contract 執行單一步驟：

```text
/wstep steps/general-auto-development/03_build.md contracts/general-auto-development/build.yaml "實作 config CRUD"
```

用 Agent slash command 搭配 contract 執行單一步驟：

```text
/wstep /build contracts/general-auto-development/build.yaml "實作 config CRUD"
```

## 重要行為

- 這些 slash command 會在 Agent CLI 裡執行 shell command。
- Qwen Code 支援專案指令 `.qwen/commands/` 與使用者指令 `~/.qwen/commands/`；專案指令優先。
- OpenCode 支援專案指令 `.opencode/commands/` 與全域指令 `~/.config/opencode/commands/`。
- 請從本專案根目錄啟動 Qwen/OpenCode，這樣 `python -m app.cli.aiwf` 才能 import 本地 `app` package。
- 啟動 Agent CLI 前，請先啟用 Python virtual environment。
- 需求文字有空白時，請用引號包起來。
- 不建議一開始就全域安裝，除非你希望所有專案都看得到 `/wf` 與 `/wstep`。
- Shell execution 可能會在 Agent CLI 內要求確認，這是正常行為。

## 疑難排解

| 問題 | 檢查 |
|---|---|
| `/wf` 沒出現 | 確認 command file 已複製到 `.qwen/commands/` 或 `.opencode/commands/`，然後重開 Agent CLI。 |
| `ModuleNotFoundError: app` | 請從本 repository root 啟動 Agent CLI，或確認目前工作目錄正確。 |
| 找不到 `python` | 啟用 `.venv`，或使用已把 Python 加入 PATH 的 shell。 |
| workflow 啟動後等很久 | `--wait` 會等待 workflow 完成；大型 workflow 本來就可能較久。 |
| OpenCode 使用自訂 config dir | 使用 `--destination <dir>/commands`，或依環境設定 `OPENCODE_CONFIG_DIR`。 |
