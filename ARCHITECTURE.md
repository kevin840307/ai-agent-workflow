# Architecture

## Goal

讓 Workflow 的 UI 與 CLI 使用同一套 filesystem-first 架構：

```text
workflow manifest + markdown skill + metadata contract + python function
```

## Canonical Asset Layout

```text
data/ai-workflow/
  workflows/**/*.workflow
  steps/**/*.md
  steps/common/**/*.md
  contracts/**/*.yaml
  contracts/**/*.json
  functions/**/*.py
```

Project local override：

```text
<project>/.ai-workflow/
  workflows/
  steps/
  contracts/
  functions/
```

解析順序永遠是：

```text
project .ai-workflow → global data/ai-workflow
```

## Main Backend Modules

```text
app/services/workflow_asset_service.py
  - canonical asset resolver
  - asset CRUD
  - workflow manifest loader
  - metadata contract mapper
  - Python function discovery

app/services/workflow_config_service.py
  - UI workflow save/load
  - converts UI workflow into workflows + contracts + steps assets

app/services/workflow_lint_service.py
  - validates workflow config before save/run

app/workflow_runtime/
  - executor, retry policy, prompt builder, step actions
  - agent provider abstraction
  - built-in Python function implementation library

app/workflow/agents/providers/
  - qwen provider
  - opencode provider
  - generic CLI provider
```

## Python Function Model

新版只有一種 Python asset：

```text
functions/**/*.py
```

metadata 使用：

```yaml
function: validate_spec
```

或：

```yaml
function: functions/check_spec.py
```

UI 下拉選單不是 hard-code catalog，而是掃描 `data/ai-workflow/functions/**/*.py` 與 project `.ai-workflow/functions/**/*.py` 的 `FUNCTION_META`。

內建 function 的執行邏輯在：

```text
app/workflow_runtime/builtin_functions/
```

它是 runtime library，不是使用者要改的設定檔。使用者新增 function 時，只要放到：

```text
data/ai-workflow/functions/
```

或：

```text
<project>/.ai-workflow/functions/
```

## Metadata Contract Fields

常用欄位：

```yaml
id: check_spec
key: check_spec
name: Check Spec
type: python
skill: steps/my-workflow/check_spec.md
function: validate_spec
agent: qwen
outputs:
  - spec.md
retry: 2
retryFromStepKey: generate_spec
failAction: selected_step
allowInteraction: false
thinking: false
confidenceThreshold: 0.9
passKeywords: PASS
failKeywords: FAIL
aggregatorFunction: keyword_confidence
```

舊版 `validator:` 僅保留 runtime 相容邏輯；新文件、UI、範例都使用 `function:`。

## UI / CLI Sharing

UI 儲存 workflow 時，會寫入：

```text
data/ai-workflow/workflows/*.workflow
data/ai-workflow/contracts/<workflow-id>/*.yaml
data/ai-workflow/steps/<workflow-id>/*.md
```

CLI 執行 workflow 時，讀取同一批 asset。

因此：

```text
UI 新增 → CLI 可跑
手動放檔案 → UI Refresh 可看到
project .ai-workflow 覆蓋 global asset
```

## Extension Rules

新增 agent provider：改 `data/settings.json` 加 provider 設定。

新增 skill：放 `steps/**/*.md`。

新增 metadata：放 `contracts/**/*.yaml`。

新增 Python function：放 `functions/**/*.py`，加 `FUNCTION_META` 可讓 UI 顯示較友善名稱。

新增 workflow：放 `workflows/*.workflow`。
