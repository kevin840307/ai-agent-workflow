# Workflow Python Function Guide

這份文件已更新為新版架構：**Python validator 與 Python tool 已合併成 Python Function**。

請優先看：

```text
PYTHON_FUNCTION_ASSET_GUIDE.md
```

新版重點：

```text
data/ai-workflow/functions/**/*.py
<project>/.ai-workflow/functions/**/*.py
```

metadata 使用：

```yaml
function: validate_spec
```

或：

```yaml
function: functions/check_spec.py
```

舊版 `validator:`、`validators/`、`tools/` 已不再是正式架構；新的 UI、文件、範例與 workflow 都使用 `function:` 或 `functions:`。
