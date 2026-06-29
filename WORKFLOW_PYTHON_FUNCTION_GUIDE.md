# 新增 Workflow Python Function 指南

這份文件說明如何新增一個 **Python Function**，讓它可以出現在 `workflow-designer` 前端下拉選單，並在 Workflow Runtime 中被執行。

---

## 1. 先理解目前架構

目前不要直接把新 function 寫在 `app/workflow_functions.py`。

`workflow_functions.py` 只是相容舊 import 的 facade：

```text
app/workflow_functions.py
  ↓ 匯出 / re-export
app/workflow_function_modules/base.py
app/workflow_function_modules/core.py
app/workflow_function_modules/security_context.py
app/workflow_function_modules/security_validation.py
app/workflow_function_modules/registry.py
```

真正新增 function 時，通常會改這三個地方：

```text
1. app/workflow_function_modules/<module>.py
   - 放真正的 Python function 實作

2. app/workflow_function_modules/registry.py
   - 註冊 function id，讓 runtime 找得到

3. app/workflow_function_catalog.py
   - 註冊前端下拉選單與 UI capability
```

心智模型：

```text
workflow_function_catalog.py  = 給前端看，控制下拉選單與 UI 顯示
registry.py                   = 給 runtime 看，控制 function id 對應到哪個 Python function
workflow_function_modules/*.py = 真正執行邏輯
WorkflowFunctionContext ctx    = function 的主要 input
ctx.output_dir                 = function 讀寫 artifact 的主要位置
raise WorkflowFunctionError    = step failed
return None                    = step success
```

---

## 2. Runtime 怎麼找到 Python Function？

Workflow step 會設定：

```json
{
  "type": "validation",
  "config": {
    "validator": "validate_spec"
  }
}
```

Runtime 會用：

```python
PYTHON_FUNCTIONS["validate_spec"]
```

找到真正的 Python function。

所以 `config.validator` 必須對到 `registry.py` 裡的 key。

---

## 3. Function input 是什麼？

Python function 的主要 input 是 `WorkflowFunctionContext`。

定義位置：

```text
app/workflow_function_modules/base.py
```

目前結構：

```python
@dataclass(frozen=True)
class WorkflowFunctionContext:
    run: dict[str, Any]
    output_dir: Path
    project_dir: Path
    root_dir: Path
    read_text: Callable[[Path], str]
    write_text: Callable[[Path, str], None]
    log: Callable[[dict[str, Any], str], Awaitable[None]]
    refresh_artifacts: Callable[[str], Awaitable[None]]
```

常用欄位：

```text
ctx.run               這次 workflow run 的資料
ctx.output_dir        runs/<run-id>/output
ctx.project_dir       使用者選擇的 project path
ctx.root_dir          平台根目錄
ctx.read_text(path)   安全讀檔 helper
ctx.write_text(path)  安全寫檔 helper
ctx.log(...)          寫 workflow log
ctx.refresh_artifacts 重新整理 artifacts
```

目前 function **沒有直接拿到 step.config 的完整內容**。

所以新增 function 時，建議先用這些 input：

```text
1. 固定讀 output_dir 裡的 artifact
2. 固定寫 output_dir 裡的新 artifact
3. 使用 project_dir 掃專案檔案
4. 使用 artifact 參數，只限特定 validator 類型
```

如果未來希望每個 Python Function 有自己的欄位，例如：

```text
targetFile
minScore
requiredSection
sqlPath
timeout
```

建議再擴充 `WorkflowFunctionContext`，讓 runtime 把 `step.config` 傳進去。

---

## 4. Function output 是什麼？

Python function 不是用 `return` 把結果回傳給前端。

目前規則：

```text
成功：return None
失敗：raise WorkflowFunctionError("錯誤原因")
輸出：寫檔到 ctx.output_dir
```

範例：

```python
ctx.write_text(ctx.output_dir / "my-result.md", "Status: DONE\n")
```

如果要讓 step failed：

```python
raise WorkflowFunctionError("my-result.md must contain Status: DONE.")
```

前端會看到 step failed，錯誤訊息就是 raise 的文字。

---

## 5. 最小範例：新增一個 Validation Function

目標：新增 `validate_my_result`，檢查 `output/my-result.md` 必須包含 `Status: DONE`。

### Step 1：新增實作

建議放在：

```text
app/workflow_function_modules/core.py
```

或新增：

```text
app/workflow_function_modules/custom.py
```

範例：

```python
from app.workflow_function_modules.base import WorkflowFunctionContext, WorkflowFunctionError


def validate_my_result(ctx: WorkflowFunctionContext) -> None:
    path = ctx.output_dir / "my-result.md"
    text = ctx.read_text(path)

    if not text.strip():
        raise WorkflowFunctionError("my-result.md is empty.")

    if "Status: DONE" not in text:
        raise WorkflowFunctionError("my-result.md must contain 'Status: DONE'.")
```

這個 function 的 contract：

```text
input:
- output/my-result.md

output:
- 無新檔案

success:
- my-result.md 存在且包含 Status: DONE

failed:
- my-result.md 空檔
- my-result.md 沒有 Status: DONE
```

---

### Step 2：註冊 runtime function

修改：

```text
app/workflow_function_modules/registry.py
```

如果 function 放在 `core.py`，先 import：

```python
from app.workflow_function_modules.core import (
    require_status_pass,
    run_pytest,
    validate_spec,
    validate_todo,
    validate_my_result,
)
```

然後加入 `PYTHON_FUNCTIONS`：

```python
PYTHON_FUNCTIONS = {
    "validate_spec": validate_spec,
    "validate_todo": validate_todo,
    "require_status_pass": require_status_pass,
    "run_pytest": run_pytest,
    "validate_my_result": validate_my_result,
}
```

key 很重要：

```text
validate_my_result
```

這個 key 會被 workflow step 的 `config.validator` 使用。

---

### Step 3：加入前端 function catalog

修改：

```text
app/workflow_function_catalog.py
```

在 `AVAILABLE_WORKFLOW_FUNCTIONS["validators"]` 加一筆：

```python
{
    "id": "validate_my_result",
    "label": "Validate My Result",
    "description": "Check output/my-result.md contains Status: DONE.",
    "ui": _ui(tabs=VALIDATOR_TABS),
}
```

這樣前端 `workflow-designer` 就會看到這個 function。

---

### Step 4：Workflow JSON 範例

```json
{
  "key": "validate_my_result",
  "title": "Validate My Result",
  "type": "validation",
  "config": {
    "validator": "validate_my_result",
    "filename": "my-result.md",
    "expectedFiles": ["output/my-result.md"]
  }
}
```

最重要的是：

```json
"validator": "validate_my_result"
```

它必須等於 `registry.py` 的 `PYTHON_FUNCTIONS` key。

---

## 6. 新增一個會產生 artifact 的 Python Function

範例：讀 `spec.md` 與 `todo.md`，產生 `python-summary.md`。

```python
from app.workflow_function_modules.base import WorkflowFunctionContext, WorkflowFunctionError


async def generate_summary_by_python(ctx: WorkflowFunctionContext) -> None:
    spec = ctx.read_text(ctx.output_dir / "spec.md")
    todo = ctx.read_text(ctx.output_dir / "todo.md")

    if not spec.strip():
        raise WorkflowFunctionError("spec.md is required before generate_summary_by_python.")

    content = "\n".join([
        "Status: DONE",
        "",
        "# Python Generated Summary",
        "",
        "## Inputs",
        f"- spec.md length: {len(spec)}",
        f"- todo.md length: {len(todo)}",
        "",
        "## Summary",
        "- Generated by Python workflow function.",
    ])

    ctx.write_text(ctx.output_dir / "python-summary.md", content)
    await ctx.refresh_artifacts(ctx.run["id"])
    await ctx.log(ctx.run, "generate_summary_by_python: wrote output/python-summary.md")
```

這個 function 的 contract：

```text
input:
- output/spec.md
- output/todo.md

output:
- output/python-summary.md

success:
- 成功寫出 output/python-summary.md

failed:
- spec.md 為空
```

registry：

```python
PYTHON_FUNCTIONS = {
    "generate_summary_by_python": generate_summary_by_python,
}
```

catalog：

```python
{
    "id": "generate_summary_by_python",
    "label": "Generate Summary by Python",
    "description": "Generate output/python-summary.md from spec.md and todo.md.",
    "ui": _ui(tabs=VALIDATOR_TABS),
}
```

workflow step：

```json
{
  "key": "generate_summary_by_python",
  "title": "Generate Summary by Python",
  "type": "python",
  "config": {
    "validator": "generate_summary_by_python",
    "filename": "python-summary.md",
    "expectedFiles": ["output/python-summary.md"]
  }
}
```

---

## 7. 什麼時候要開 Prompt UI？

現在 Step UI 已改成 config-driven。

前端會看 `app/workflow_function_catalog.py` 裡的 `ui` metadata。

### 不需要 Prompt 的 function

例如純檢查檔案：

```python
"ui": _ui(tabs=VALIDATOR_TABS)
```

效果：

```text
不顯示 Prompt tab
不顯示 Agent Provider
```

---

### 需要 Prompt + Agent Provider 的 function

例如 Python function 內部會包 agent 執行，或需要 prompt template：

```python
{
    "id": "my_agent_function",
    "label": "My Agent Function",
    "description": "Run custom Python-backed agent function.",
    "ui": _ui(
        supports_prompt=True,
        supports_agent=True,
        tabs=PROMPT_AGENT_TABS,
        prompt_defaults=True,
    ),
}
```

效果：

```text
顯示 Prompt tab
顯示 Agent Provider
切換 function 時會補 prompt defaults
```

常用 tab：

```python
PROMPT_AGENT_TABS = ["basic", "sources", "retry", "advanced"]
REVIEW_AGENT_TABS = ["basic", "sources", "review", "retry", "advanced"]
VALIDATOR_TABS = ["basic", "retry", "advanced"]
```

---

## 8. Artifact validator：需要第二個參數 artifact 的情境

大部分 function 只吃一個參數：

```python
def my_function(ctx: WorkflowFunctionContext) -> None:
    ...
```

少數 validator 會吃第二個參數 `artifact`：

```python
def validate_custom_artifact(ctx: WorkflowFunctionContext, artifact: str) -> None:
    text = ctx.read_text(ctx.output_dir / artifact)
    ...
```

目前 runtime 只有對特定 function id 傳 artifact。

位置：

```text
app/workflow_runtime/actions.py
```

目前類似這樣：

```python
artifact_validators = {
    "require_status_pass",
    "validate_security_candidates",
    "validate_security_report",
}
```

如果你新增：

```python
def validate_custom_artifact(ctx, artifact):
    ...
```

你還要把 id 加進 `artifact_validators`：

```python
artifact_validators = {
    "require_status_pass",
    "validate_security_candidates",
    "validate_security_report",
    "validate_custom_artifact",
}
```

不然 runtime 只會呼叫：

```python
function(ctx)
```

而不是：

```python
function(ctx, artifact)
```

建議一開始先避免 artifact 參數，直接讀固定檔案最簡單：

```python
def validate_my_result(ctx):
    text = ctx.read_text(ctx.output_dir / "my-result.md")
```

---

## 9. Step Type 怎麼選？

常用選擇：

```text
validation  適合檢查 artifact，失敗時 step failed
python      適合執行 deterministic Python job，例如產檔、跑測試、合併結果
ai          適合純 agent prompt
review      適合 review prompt
command     適合 command prompt
```

目前 runtime 對 `validation` 有一些特殊邏輯：

```text
validate_spec  會走 validate_or_repair_spec
validate_todo  會走 validate_or_repair_todo
consensus_agent 會走 consensus_agent_step
其他 registered Python function 會走 call_python_function
```

如果你只是新增一般 Python function，通常用：

```json
{
  "type": "python",
  "config": {
    "validator": "your_function_id"
  }
}
```

如果你是新增 validation checker，通常用：

```json
{
  "type": "validation",
  "config": {
    "validator": "your_function_id"
  }
}
```

---

## 10. 新增 Function Checklist

新增一個 function 前，照這份 checklist 做。

```text
[ ] 1. 決定 function id
       例如：validate_my_result

[ ] 2. 決定 function 類型
       validation / python / agent-backed python

[ ] 3. 實作 function
       app/workflow_function_modules/core.py
       或 app/workflow_function_modules/custom.py

[ ] 4. function 簽名正確
       def xxx(ctx: WorkflowFunctionContext) -> None
       或 async def xxx(ctx: WorkflowFunctionContext) -> None

[ ] 5. 失敗時 raise WorkflowFunctionError

[ ] 6. 成功時 return None

[ ] 7. 需要輸出時寫到 ctx.output_dir

[ ] 8. registry.py 加入 PYTHON_FUNCTIONS

[ ] 9. workflow_function_catalog.py 加入前端下拉選單

[ ] 10. catalog ui 設定正確
        不用 prompt：_ui(tabs=VALIDATOR_TABS)
        要 prompt：_ui(supports_prompt=True, supports_agent=True, tabs=PROMPT_AGENT_TABS, prompt_defaults=True)

[ ] 11. 如果 function 需要 artifact 參數，要改 actions.py 的 artifact_validators

[ ] 12. 新增或更新測試

[ ] 13. 跑測試
        python -m compileall app tests
        python -m unittest discover -s tests -q
```

---

## 11. 常見錯誤

### 錯誤 1：前端看得到，但 runtime 說 Unknown function

原因：只加了 `workflow_function_catalog.py`，沒加 `registry.py`。

修正：

```python
PYTHON_FUNCTIONS["your_function_id"] = your_function
```

---

### 錯誤 2：runtime 有註冊，但前端看不到

原因：只加了 `registry.py`，沒加 `workflow_function_catalog.py`。

修正：在 catalog 的 `validators` 或其他對應清單加一筆。

---

### 錯誤 3：function 需要 artifact，但 runtime 沒傳

原因：沒有把 function id 加進 `artifact_validators`。

修正：改 `app/workflow_runtime/actions.py`。

---

### 錯誤 4：step 成功但前端 artifacts 沒刷新

原因：function 寫檔後沒有呼叫：

```python
await ctx.refresh_artifacts(ctx.run["id"])
```

如果是 sync function，又需要刷新，可以改成 async function。

---

### 錯誤 5：function 裡直接用 open 讀寫檔

建議用：

```python
ctx.read_text(path)
ctx.write_text(path, content)
```

這樣比較符合專案現有 runtime helper。

---

## 12. 建議命名規則

```text
validate_xxx     檢查 artifact，失敗 raise error
collect_xxx      收集資料，寫出 context artifact
combine_xxx      合併多份 artifact
generate_xxx     產生 deterministic artifact
finalize_xxx     最終整理輸出
run_xxx          執行外部工具或測試
```

範例：

```text
validate_spec
validate_todo
collect_security_context
combine_security_candidates
generate_security_report
finalize_security_report
run_pytest
```

---

## 13. 最推薦的新增方式

如果只是要新增一個普通 Python function，建議照這個最小路徑：

```text
1. 寫 function：
   app/workflow_function_modules/core.py

2. 註冊 runtime：
   app/workflow_function_modules/registry.py

3. 註冊前端：
   app/workflow_function_catalog.py

4. workflow step 用：
   type = python
   config.validator = function id
```

最小 JSON：

```json
{
  "key": "my_python_step",
  "title": "My Python Step",
  "type": "python",
  "config": {
    "validator": "my_python_function"
  }
}
```

最小 Python：

```python
from app.workflow_function_modules.base import WorkflowFunctionContext, WorkflowFunctionError


def my_python_function(ctx: WorkflowFunctionContext) -> None:
    ctx.write_text(ctx.output_dir / "my-output.md", "Status: DONE\n")
```

最小 registry：

```python
PYTHON_FUNCTIONS = {
    "my_python_function": my_python_function,
}
```

最小 catalog：

```python
{
    "id": "my_python_function",
    "label": "My Python Function",
    "description": "Write output/my-output.md.",
    "ui": _ui(tabs=VALIDATOR_TABS),
}
```
