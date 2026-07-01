# AI Workflow MVP Mode

本專案已統一成 `.ai-workflow` asset 模式。UI 與 CLI 共用同一套 resolver，不再有兩套 workflow source of truth。

## Canonical Global Root

```text
data/ai-workflow/
  workflows/     # workflow manifest: *.workflow
  steps/         # markdown skill / prompt assets
    common/      # global shared markdown, every workflow can reference
  contracts/     # metadata YAML/JSON
  functions/     # Python Function assets
```

## Project Override Root

```text
<project>/.ai-workflow/
  workflows/
  steps/
    common/
  contracts/
  functions/
```

解析順序：

```text
1. project/.ai-workflow/*
2. data/ai-workflow/*
```

所以你可以把公司共用 skill、metadata、function 放在 `data/ai-workflow`，所有 workflow 都能用；專案要覆蓋時，放在專案 `.ai-workflow` 即可。

## Workflow Manifest

```yaml
id: my-workflow
name: My Workflow
description: Example workflow
steps:
  - contract: contracts/my-workflow/generate_spec.yaml
  - contract: contracts/my-workflow/check_spec.yaml
```

簡寫也支援：

```text
contract: contracts/my-workflow/generate_spec.yaml
step: steps/common/human-interaction-rule.md
@other-workflow
workflow: other-workflow
```

## Metadata Contract

```yaml
id: generate_spec
key: generate_spec
name: Generate Spec
type: ai
skill: steps/my-workflow/generate_spec.md
agent: qwen
outputs:
  - spec.md
retry: 2
allowInteraction: false
thinking: false
```

Python Function step：

```yaml
id: check_spec
key: check_spec
name: Check Spec
type: python
function: validate_spec
retry: 2
retryFromStepKey: generate_spec
failAction: selected_step
```

或直接引用 function asset：

```yaml
function: functions/check_spec.py
```

## Function Asset

```python
FUNCTION_META = {
    "id": "check_spec",
    "label": "Check Spec",
    "description": "Check spec.md required sections.",
}


def run(context, artifact=None):
    text = context.read_text(context.output_dir / (artifact or "spec.md"))
    if "AC-001" not in text:
        raise Exception("spec.md missing AC-001")
    return "Status: PASS\n"
```

UI 會掃描 `functions/**/*.py` 的 `FUNCTION_META`，自動產生 Python Function 下拉選單。

## Global Shared Markdown

建議共用規則、共用 prompt 片段放：

```text
data/ai-workflow/steps/common/*.md
```

任何 workflow metadata 可直接引用：

```yaml
skill: steps/common/human-interaction-rule.md
```

## UI

Workflow Designer 的 `.ai-workflow Assets` 支援：

```text
steps / contracts / functions / workflows
```

可操作：

```text
List / Create / Read / Update / Delete / Rename / Upload / Apply to Step
```

手動新增檔案後，按 Refresh，UI 會看到。

## CLI

CLI 與 UI 共用同一套 backend resolver：

```bash
python -m app.cli.aiwf run --workflow my-workflow --requirement requirement.md
```

## qwen / opencode / generic CLI

agent provider 設定在：

```text
data/settings.json
```

metadata 用：

```yaml
agent: qwen
```

或：

```yaml
agent: opencode
```

可擴充新的 provider，不需要改 workflow asset 格式。
