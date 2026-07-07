# Real Agent Smoke

Mock E2E validates the controller. Real smoke validates Qwen/OpenCode behavior.

First run a self-prompt check:

```bash
python scripts/run_real_agent_smoke.py --self-prompt-test --agent qwen --workflow adaptive-auto-workflow --case sort
```

Then run a real agent smoke when Qwen/OpenCode is available:

```bash
python scripts/run_real_agent_smoke.py --agent qwen --workflow adaptive-auto-workflow --case sort
python scripts/run_real_agent_smoke.py --agent qwen --workflow general-auto-development --case config-loader
python scripts/run_real_agent_smoke.py --agent opencode --workflow adaptive-auto-workflow --case readme
```

The script refuses real runs when `QWEN_MOCK=1`, unless `--allow-mock` is explicitly provided.

## Self-Prompt Workflow E2E

Use this when Qwen/OpenCode is not available but you still want to prove that the workflow controller can run the same user prompt through both system workflows and capture real workflow logs.

```bash
python scripts/run_self_prompt_workflow_e2e.py self-prompt-workflow-e2e-logs
```

This script runs both workflows through the FastAPI workflow-run API:

- `general-auto-development`
- `adaptive-auto-workflow`

It uses this prompt:

```text
幫我用python寫氣泡排序法+選擇排序法+插入排序法+快速排序法+合併排序法+堆積排序法+希爾排序法
```

Artifacts written by the script:

```text
self-prompt-workflow-e2e-logs/
├── summary.json
├── workflow-console.log
├── general-auto-development/
│   ├── run.json
│   ├── timeline.txt
│   ├── steps.json
│   ├── project-snapshot/
│   └── run-workspace/
└── adaptive-auto-workflow/
    ├── run.json
    ├── timeline.txt
    ├── steps.json
    ├── project-snapshot/
    └── run-workspace/
```

Pytest entry:

```bash
python -m pytest tests/test_self_prompt_workflow_e2e.py -q
```
