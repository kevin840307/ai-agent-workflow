# Test Pipeline and Run Lifecycle Hardening

This round focuses on production-readiness items 2 and 4:

1. Stabilize the full test pipeline.
2. Harden workflow run locking, cancellation, timeout handling, and restart recovery.

## Test pipeline

The test suite is now treated as a CI matrix instead of one long Python interpreter.

### Why

Workflow tests use FastAPI `TestClient`, background workflow tasks, and subprocess-style agent mocks. A single `pytest -q` process can keep event-loop or shutdown state alive across unrelated tests. That makes the suite appear hung even when the same tests pass in clean interpreters.

### Runner

Use:

```bash
python scripts/run_tests.py --list-groups
python scripts/run_tests.py --group A_core_cli_api
python scripts/run_tests.py --group B_general_project_prompt
python scripts/run_tests.py --group C_productization_features
python scripts/run_tests.py --group D_manual_run_state
python scripts/run_tests.py --group E_runtime_safety_contracts
python scripts/run_tests.py --group F_workflow_assets_stability
python scripts/run_tests.py --group G_workflow_e2e_contracts
```

Each group gets:

- a fresh Python interpreter
- a dedicated `AIWF_STORE_FILE`
- real-agent environment variables disabled by default
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`

`coverage_report()` also verifies that every `tests/test_*.py` file is assigned to exactly one group, so newly added tests cannot silently be skipped by the grouped pipeline.

## Run lifecycle hardening

### Persistent project run lock

Each active run writes:

```text
.qwen-workflow/project-run-lock.json
```

The lock records:

- run id
- session id
- workflow id
- original project path
- effective project path
- process owner
- updated timestamp

The lock is cleared when the run reaches `done`, `failed`, or `cancelled`. Stale locks are cleaned before creating a new run for the same project.

### Project-level run guard

Only one active workflow can run against the same original project path at a time. This avoids two agents modifying the same project concurrently.

### Cancellation

`POST /api/workflow-runs/{run_id}/cancel` now marks the run as `cancelling`, persists `cancel_requested`, attempts to terminate the tracked agent process, escalates to kill if needed, and cancels the workflow task. The executor checks cancellation before and after every step.

### Timeout

Run-level `runTimeoutSec` wraps the whole workflow. On timeout, the service terminates or kills the tracked agent process, marks the run as failed with `TIMEOUT`, refreshes artifacts, and publishes a failure event.

Step-level timeout remains enforced by the executor with `asyncio.wait_for`.

### Restart recovery

On server startup, stale queued/running/cancelling runs owned by the previous dead process are marked failed and retryable. Recovery now mirrors the state to:

```text
.workflow/state.json
.workflow/run-log.md
```

and clears the project lock so the project is not permanently blocked after a server restart.

### Lifecycle API

```text
GET /api/workflow-runs/{run_id}/lifecycle
```

Returns:

- run status
- project lock data
- cancel request state
- run timeout
- restart recoverability
- active task/process flags
