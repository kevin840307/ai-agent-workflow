# Architecture

## Responsibility boundary

```text
Qwen/OpenCode
  understand, plan, edit files from the effective Project Path cwd, repair, review

Workflow kernel
  deterministic state, task contracts, retry/recovery routing, sessions,
  checkpoints, validation, atomic delivery, evidence

FastAPI/Web UI/CLI
  project/run operation, Simple/Advanced presentation, diagnostics, assets
```

The controller never implements the requested product feature. It may inspect, snapshot, compare, validate, copy verified Agent output during atomic delivery, and roll back, but it does not synthesize requested source code.

## Canonical runtime

- `app/workflow_engine/`: state machine and executor contracts.
- `app/workflow_runtime/`: Agent actions, validation, retry, context, checkpoints, Autopilot state, preflight, environment health, profiles, atomic delivery, and evidence.
- `app/services/`: use-case APIs and recovery coordination.
- `app/workflow/agents/providers/`: Qwen, OpenCode, and generic CLI adapters.
- `app/persistence/`: SQLite WAL store and normalized run projections.

`app/runtime_modules/` is a quarantined low-level compatibility boundary. New orchestration must not be added there.

## Autopilot state machine

Unattended runs persist compact, UI-independent states:

```text
discovering → executing → finalizing → verified → completed
```

For engineering Workflows, preflight resolves environment health, reusable Project Validation Profile, and baseline evidence. Report-only Workflows may declare `validationBaseline: false` and skip unrelated Build/Test baseline execution. Every important transition is persisted so restart recovery can distinguish a resumable interrupted run from an unsafe or terminal run.

## Project and session isolation

- Normal Agent processes use `cwd = selected Project Path`.
- Isolated unattended runs use a copied effective Project Path that preserves project-local CLI configuration.
- One active writer is allowed per original project.
- Different projects/sessions can run concurrently through provider semaphores.
- Planning, implementation, validation, and review can use role-scoped sessions.
- Context overflow or repeated failure can rotate to a fresh session using compact handoff evidence.

## Baseline and validation profile

Profiles are keyed by the resolved Project Path and stored under controller data. Descriptor fingerprints cover supported build/test/validation descriptors. Profile commands are executed from the effective Project Path; no language-specific command is embedded in workflow definitions.

Baseline evidence separates pre-existing failures from regressions introduced by the current run. Completion blocks new or worsened failures, not unrelated unchanged legacy failures.

## Progress-aware recovery

Recovery uses both failure identity and progress identity. The progress signature includes filesystem state, changed files, task state, validation evidence, and checkpoints. A repeated failure with improving evidence may continue; the same failure with the same progress signature triggers strategy/session rotation and eventually a cumulative budget stop.

## Atomic delivery

For isolated unattended runs:

```text
snapshot original → Agent edits isolated effective Project Path → validate
→ detect original-project conflicts → atomically copy only verified Agent changes
→ post-apply fast validation → keep or rollback
```

Atomic delivery copies Agent-created bytes; it does not generate file content. If the original project changed externally or post-apply validation regresses, the delivery is rejected or rolled back.

## Connectivity and durable recovery

Provider connectivity is probed independently from the workflow event stream. Transient connection failures wait at low frequency for unattended runs and do not rapidly consume Agent retries. EventSource reconnects automatically and rehydrates current run state after reconnection.

At controller startup, interrupted unattended runs with safe persisted recovery metadata are automatically resumed. Idempotent checkpoints and project locks prevent duplicate writers.

## Evidence and storage

SQLite uses WAL and normalized tables for runs, steps, tasks, sessions, events, validation results, file changes, checkpoints, and locks. A compatibility document snapshot remains for atomic recovery; queries use projections. Schema evolution is ordered by `app/persistence/migrations.py`: one transaction per version, automatic pre-migration backup for existing data, rollback on failure, exact-version verification, and rejection of databases newer than the running controller. Sensitive values are redacted before persistence/display.

## Frontend layout boundary

Simple and Advanced Mode share one state tree. Run Center owns readable Overview and Validation. Overview opens one near-fullscreen Patch Review workbench; normal approval/apply is not duplicated inside Technical Diagnostics. Diagnostics owns Agent output, logs, repair evidence, process/session health, Delivery/Rollback evidence, and the shared Execution Artifacts viewer. Every work surface owns its scrolling; no nested fixed-height panel may compress another workspace.

## Frontend module boundaries

```text
static/js/pages/
├── workflow-designer.js             # thin page entry
├── workflow-designer/
│   ├── controller.js
│   ├── asset-tools.js
│   ├── layout-renderer.js
│   ├── step-settings-renderer.js
│   ├── template-editor.js
│   ├── import-export.js
│   ├── function-catalog.js
│   ├── model.js
│   └── utils.js
├── ai-workflow-assets.js
└── ai-workflow-assets/
    └── asset-manager.js
```

Page entries stay thin. State, rendering, asset editing, and interaction logic remain in focused modules so UI fixes do not grow one monolithic page script.

## Runtime context and compatibility facade

`app/core/runtime_context.py` is the explicit container for controller-owned services: Store, Event Bus, Run State, Task/Process registries, Agent Manager, Actions, Executor, and Kernel. `app/runtime_modules/api.py` remains a compatibility facade for existing routes and tests, but new orchestration should request `get_runtime_context()` rather than adding more mutable module-global imports.

This is an incremental migration boundary. FastAPI lifecycle, repository access, health, maintenance, project/session APIs, and event streams now consume the context directly. Provider-backed compatibility properties preserve existing integrations that patch the legacy facade while the remaining services migrate one at a time.

## Failure Contract V3

Runtime producers should emit deterministic error codes. `aiwf.failure.v3` carries code, source/provider, retry target, severity, evidence references, raw diagnostics, and classification source. Retry/UI/reporting consume the code; provider message matching is only a compatibility adapter for CLI output that cannot emit structured errors.

## Executor stage boundary

The main executor loop owns sequencing and lease-safe attempt completion. Failed-step recovery is isolated in `_recover_failed_step()`, which owns retry budget, target escalation, loop guard, fresh-session rotation, feedback, and reset synchronization. Agent tool-call JSON parsing is isolated in `agent_output_parser.py` and never executes model-emitted tool JSON.

## Command execution boundary

Synchronous controller commands use `app/core/command_runner.py`. It classifies commands as trusted, project-scoped, or Agent-generated; validates cwd, controls shell use, terminates process trees on timeout, bounds output, normalizes UTF-8, and redacts secrets. Agent CLI streaming remains in `ProcessSupervisor`, which owns heartbeat/stall handling and process registration. New code must not add an independent `subprocess.run(..., shell=True)` path.

## Test catalog boundary

`app/testing/test_catalog.py` is the source of test groups, tiers, and named profiles. Pytest collection assigns every file a stable `unit`, `contract`, `integration`, `e2e`, `manual`, `real_agent`, or `soak` marker. Manual/real-Agent files are excluded from normal developer and commit profiles.
