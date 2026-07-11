# System Optimization V8

V8 turns Agent Workflow Web from a raw-log and artifact-heavy developer tool into a recoverable, evidence-driven local workflow product. It preserves the V7 Project Path, filesystem-first, phase ownership, and deterministic repair behavior while unifying state, sessions, workspace policy, validation, evidence, and the main operating UI.

## Product experience

The normal flow is now:

1. Select a Project Path.
2. Enter a requirement.
3. Optionally apply the execution recommendation.
4. Run the workflow.
5. Review Overview, Changes, and Validation.

Console, prompts, session IDs, patch JSON, the artifact index, repair policy, and debug data are moved into a lazy-loaded Technical Diagnostics drawer.

## Unified architecture

| Responsibility | Implementation |
|---|---|
| Planner | workflow assets and General/Adaptive planners |
| State machine / orchestrator | `workflow_engine/state_machine.py`, executor, checkpoints |
| Workspace manager | snapshots, run diff, phase ownership, test-layout repair |
| Session manager | planning/build/validation/review role sessions |
| Policy engine | project guard, read-only planning/review, write ownership |
| Validation engine | syntax, pytest, validation.py, hygiene, evidence review |
| Evidence store | SQLite v2 normalized projections and compact artifacts |

General and Adaptive keep different planning strategies but share the same execution, session, retry, workspace, validation, and evidence kernel.

## Reliability core

- Explicit run and step transitions with bounded transition history.
- A checkpoint after every successful step.
- Restart recovery from the most recent checkpoint.
- Project write locks cleared consistently on stop, cancel, crash recovery, and shutdown.
- Role-scoped sessions; planning and review are always fresh and read-only.
- Timeout and rollback recovery use a fresh session.
- Context-limit recovery can hand off a compact summary to a fresh session.
- Atomic file writes use temporary files, fsync, and atomic replace.
- SQLite uses WAL, busy timeout, foreign keys, migrations, and backup.

## Validation and policy

Validation order:

```text
Path/permission
→ syntax/compile
→ test-layout preflight
→ unit tests
→ user validation script
→ project hygiene
→ acceptance evidence
→ read-only AI review
→ final gate
```

Build and Generate Tests have different file ownership. Valid changes are preserved while only out-of-phase edits are restored. Python source without an executable validation target returns `VALIDATION_NOT_EXECUTED` instead of a false PASS.

## Retry and errors

Typed errors include session, context, timeout, path policy, test layout, test failure, invalid output, review mutation, duplicate implementation, and interruption cases.

Recovery is reported using separate counters for agent attempts, automatic/deterministic repair, session restarts, replans, manual actions, and consecutive failures. A successful step clears only the failure streak; cumulative history remains available for analytics.

## Compact artifacts

`AIWF_ARTIFACT_MODE=compact` is the default. It avoids per-step JSON copies and redundant console/state/event mirrors. Normal users see only final reports, changes, tests, validation, and gates. Verbose diagnostics can be packed into one `diagnostics.zip`; optional pruning removes redundant mirror folders.

## Run Center

The main detail area is reduced to:

- Overview: current action, reason, next step, progress, friendly step names, completion summary.
- Changes: added/modified/removed files, source step, diff, automatic cleanup.
- Validation: compile, tests, validation script, hygiene, review, final gate.

Technical Diagnostics loads console/timeline, agent logs, all artifacts, patch review/apply, repair policy, setup, analytics, SQLite projection, and a compact debug JSON only when opened.

## Setup and intelligent recommendations

Setup status reports seven readiness checks: storage, Project Path write, Agent CLI, model configuration, context window, session recovery, and tool calling.

The optimizer recommends workflow, agent, run profile, thinking level, task range, time range, local compute cost, prompt budget, successful templates, and repair strategies. Recommendations are advisory and require the user to click Apply.

## Key APIs

- `GET /api/setup/status`
- `POST /api/setup/smoke`
- `POST /api/optimization/recommend`
- `GET /api/analytics/summary`
- `GET /api/workflow-runs/{id}/overview`
- `POST /api/workflow-runs/{id}/actions`
- `GET /api/workflow-runs/{id}/diagnostics`
- `POST /api/workflow-runs/{id}/artifacts/compact`
- `GET /api/maintenance/store/status`
- `POST /api/maintenance/store/backup`

## Testing

V8 covers state transitions, role sessions, SQLite projection and backup, lock lifecycle, restart recovery, compact artifacts, typed errors, Run Center and diagnostics UI contracts, setup, optimization, both core workflows, validation, safety, path guards, and browser static smoke. Real Qwen CLI, Playwright, and clean-repository tests remain opt-in.
