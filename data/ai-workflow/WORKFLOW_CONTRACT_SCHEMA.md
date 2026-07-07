# Workflow / Step Contract Schema

Every workflow should be understandable by the controller without hardcoded workflow-specific logic.

## Workflow fields

- `id`: stable workflow id.
- `version`: optional semantic or timestamp version.
- `steps`: ordered step contracts.

## Step fields

- `key`: stable step key, unique within the workflow.
- `type`: `ai`, `review`, `python`, `validation`, `check`, `gate`, `manual`, `command`, `agent`, or `qwen`.
- `templatePath` / `skill`: prompt template for agent/review steps.
- `contractPath`: metadata contract for the step.
- `function` / `functions`: deterministic Python runtime functions.
- `outputFile` / `filename`: primary artifact.
- `expectedFiles`: artifacts or project files expected after the step.
- `retryFromStepKey`: target step when the current step fails.
- `maxRetries` / `retry`: retry budget.

Run:

```bash
python scripts/validate_workflow_assets.py
```

The validator emits `aiwf.workflow-validator.v3` and normalized `step_contracts` for every workflow.
