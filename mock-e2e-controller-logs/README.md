# Mock E2E Workflow Logs

This folder contains deterministic mock E2E runs for the AI Workflow Controller cleanup.

## Results
- adaptive-auto-workflow: PASS
- general-auto-development: PASS

## Useful files
- summary.json: overall E2E result.
- <workflow>/timeline.txt: high-level step sequence.
- <workflow>/run-workspace/prompts/*.md: prompts sent to the mock CLI agent.
- <workflow>/run-workspace/.workflow/run-log.md: chronological workflow log.
- <workflow>/run-workspace/.workflow/state.json: final run state.
- <workflow>/run-workspace/output/: artifacts produced by workflow steps.
- <workflow>/project-snapshot/: final project files after the workflow.

## Session behavior
Both workflows reuse one agent session per run. Retry prompts are configured to stay in the same session and send concise failure feedback only.
