# Python Function Asset Guide

新版只有一種 Python asset：**Python Function**。

舊欄位與舊資料夾：

```text
validator: ...      # 舊版相容，不建議再用
validators/        # 已移除
 tools/            # 已移除
```

新版統一使用：

```text
function: ...
functions/**/*.py
```

## 1. 目錄

全域共用：

```text
data/ai-workflow/functions/**/*.py
```

專案覆蓋或專案專用：

```text
<project>/.ai-workflow/functions/**/*.py
```

解析順序：

```text
1. project/.ai-workflow/functions
2. data/ai-workflow/functions
```

所以你可以把公司共用 function 放在 `data/ai-workflow/functions`，每個 workflow 都能用。某個專案想覆蓋同名 function 時，放在該專案 `.ai-workflow/functions` 即可。

## 2. Function 檔案格式

最小格式：

```python
def run(context, artifact=None):
    text = context.read_text(context.output_dir / (artifact or "spec.md"))
    if "## Goal" not in text:
        raise Exception("spec.md must contain ## Goal")
```

建議格式：

```python
FUNCTION_META = {
    "id": "check_spec",
    "label": "Check Spec",
    "description": "Check spec.md required sections.",
    "ui": {"tabs": ["basic", "retry", "advanced"]},
}


def run(context, artifact=None):
    target = context.output_dir / (artifact or "spec.md")
    text = context.read_text(target)
    if "## Goal" not in text:
        raise Exception("spec.md missing ## Goal")
    return "Status: PASS\n"
```

`FUNCTION_META` 會被 UI 掃描，出現在 Python Function 下拉選單。

## 3. context 可用能力

```python
context.run            # run 狀態 dict
context.output_dir     # workspace/output
context.project_dir    # 使用者選擇的 Project Path
context.root_dir       # app root
context.read_text(path)
context.write_text(path, content)
await context.log(context.run, "message")
await context.refresh_artifacts(context.run["id"])
```

同步或 async 都可：

```python
async def run(context, artifact=None):
    await context.log(context.run, "checking...")
```

## 4. metadata 怎麼引用

用 function id：

```yaml
id: validate_spec
name: Validate Spec
type: python
function: validate_spec
retry: 2
retryFromStepKey: generate_spec
failAction: selected_step
```

或用 function 檔案路徑：

```yaml
id: check_spec
name: Check Spec
type: python
function: functions/check_spec.py
outputs:
  - spec-check.md
```

## 5. 失敗與 retry

Function 只要丟 Exception 就會失敗，錯誤訊息會進入 retry feedback：

```python
def run(context, artifact=None):
    raise Exception("Missing AC-001 in spec.md")
```

搭配 metadata：

```yaml
retry: 3
retryFromStepKey: generate_spec
failAction: selected_step
injectFailureFeedback: true
```

## 6. 輸出檔案

Function 可以直接寫 output：

```python
def run(context, artifact=None):
    context.write_text(context.output_dir / "summary.md", "Status: DONE\n")
```

如果 `run()` 回傳字串，runtime 會寫成：

```text
output/<function-file-name>-result.md
```

## 7. UI 使用方式

在 Workflow Designer：

```text
.ai-workflow Assets → Type = Python Function
```

支援：

```text
List / Create / Read / Update / Delete / Rename / Upload
```

新增或手動放檔案後，按 **Refresh**，UI 就會看到。

## 8. CLI 使用方式

Workflow metadata 裡使用 `function:` 後，CLI 與 UI 走同一套 resolver：

```bash
python -m app.cli.aiwf run --workflow my-workflow --requirement requirement.md
```

CLI 不需要額外註冊 function。

## 9. 全域共用 Markdown

全域共用 markdown 建議放：

```text
data/ai-workflow/steps/common/*.md
```

任何 workflow 都能引用：

```yaml
skill: steps/common/human-interaction-rule.md
```

專案覆蓋：

```text
<project>/.ai-workflow/steps/common/human-interaction-rule.md
```
