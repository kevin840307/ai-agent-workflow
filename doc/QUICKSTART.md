# Quickstart

This project is an AI Workflow Controller. It does not replace Qwen/OpenCode; it simulates a human sending concise prompts, then controls retry, review, validation, and observability.

## 1. Create or choose a project

Use a normal project folder. The controller stores run files under:

```text
<Project Path>/.ai-workflow/runs/
```

## 2. Start the app

```bash
python -m app.main
```

Open the web UI and choose a project.

## 3. Pick a workflow

Use:

- `adaptive-auto-workflow` for flexible one-shot tasks where AI plans the prompts.
- `general-auto-development` for fixed SOP development: Plan Tasks -> Execute Loop -> Review -> Validation -> Final Gate.

## 4. Enter the requirement

Write the task as if you were typing to Qwen/OpenCode CLI.

Example:

```text
Create sort_utils.py with bubble_sort(data), and add focused tests.
```

## 5. Optional validation script

In Advanced / Validation, set:

```text
validation.py
```

If empty, the workflow auto-detects `validation.py`, `validate.py`, `verify.py`, or `check.py`; otherwise validation is skipped as PASS.

## 6. Run and inspect

Use the Timeline and Step Details panels to inspect:

- Effective Prompt
- Prompt Meta
- Agent Output
- Changed Files
- Gate Report
- Retry History

## 7. Manual recovery

When a run fails, you can:

- Retry from selected step
- Add guidance
- Skip step
- Mark step passed
- Resume from selected step
- Export run bundle
- Replay run
