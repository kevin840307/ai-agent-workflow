# Refactor Architecture Notes

This file is intentionally short. The old workflow bundle and old Python validator/tool split were removed.

Current source of truth:

```text
data/ai-workflow/workflows/
data/ai-workflow/steps/
data/ai-workflow/contracts/
data/ai-workflow/functions/
```

Project override:

```text
<project>/.ai-workflow/
```

Python validator and Python tool are now a single concept: **Python Function**. New metadata uses `function:`.

See:

```text
ARCHITECTURE.md
AI_WORKFLOW_MVP_MODE.md
PYTHON_FUNCTION_ASSET_GUIDE.md
```
