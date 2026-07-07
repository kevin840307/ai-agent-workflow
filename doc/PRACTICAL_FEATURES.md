# Practical Workflow Features

This release turns the next most useful platform ideas into explicit, testable features.

## 1. Failure Classifier

Endpoint:

```text
GET /api/workflow-runs/{run_id}/failures
```

Canonical classes include:

- `NO_FILE_CHANGE`
- `VALIDATION_FAILED`
- `TEST_FAILED`
- `REVIEW_FAILED`
- `TIMEOUT`
- `INVALID_OUTPUT`
- `PROJECT_GUARD_BLOCKED`
- `EXPECTED_FILES_MISSING`

The classifier is also written into retry feedback and gate/trace artifacts so the next repair prompt receives a concrete failure class.

## 2. Resume / Re-run Step

Endpoint:

```text
POST /api/workflow-runs/{run_id}/steps/rerun
```

Body:

```json
{
  "step_key": "build",
  "mode": "from_step",
  "reason": "repair after validation failure"
}
```

Supported modes:

- `from_step`
- `current_step`
- `validation_only`

The existing `/retry` and `/resume` endpoints remain supported.

## 3. Run Diff Viewer

Endpoint:

```text
GET /api/workflow-runs/{run_id}/diff
```

Artifacts:

```text
.workflow/project-snapshot-before.json
.workflow/run-diff.json
.workflow/run-diff.md
```

The UI exposes `Diff` in the result panel and `Run Diff` in Debug tools mode.

## 4. Case Library

Endpoints:

```text
GET /api/workflow-cases
GET /api/workflow-cases/{case_id}
```

Script:

```bash
python scripts/run_workflow_case_library.py --dry-run
python scripts/run_workflow_case_library.py --execute --output workflow-case-library-logs
```

Each case is a folder containing `requirement.md`, optional `validation.py`, and `expected_behavior.json`.

## 5. Real Agent Smoke Test Center

Script:

```bash
python scripts/run_real_agent_smoke.py --list-cases
python scripts/run_real_agent_smoke.py --self-prompt-test --case sort
python scripts/run_real_agent_smoke.py --agent qwen --workflow adaptive-auto-workflow --case sort
```

Outputs include:

```text
summary.json
self-prompt-review.json
real-agent-smoke-report.md
run.json
run-workspace/
project-snapshot/
```

## 6. Validation Script Generator

Endpoint:

```text
POST /api/validation-scripts/generate
```

Body:

```json
{
  "requirement": "幫我用 python 寫七種排序法",
  "expectedResult": "七個 function 都要回傳 sorted list",
  "projectPath": "C:/project-a",
  "write": true,
  "filename": "validation.py"
}
```

The generator creates a deterministic Python validation script and can optionally write it to the selected project.
