# System Productization V9

V9 moves AI Workflow Controller from a workflow demo toward a local product that can run long agent tasks safely and remain understandable to normal users.

## Product goals

- Keep the primary screen focused on the requirement, current action, file changes, and validation.
- Make recommendations, environment warnings, and completion notices dismissible and non-blocking.
- Treat the filesystem, deterministic validators, and accepted checkpoints as sources of truth.
- Continue a task after context exhaustion or controller restart without replaying completed work.
- Require human approval for high-risk changes while preserving a fully automatic path for low-risk work.
- Support Qwen, OpenCode, and future agents through a common adapter contract.
- Measure every release against a fixed regression benchmark catalog.

## Normal user flow

```text
Select project
→ describe the requirement
→ optionally open/apply the compact recommendation
→ start the workflow
→ follow Current Action and Timeline
→ review Changes and Validation
→ approve/apply a patch only when required
→ open Technical Diagnostics only for troubleshooting
```

### Non-blocking UI

- The execution recommendation is a compact sparkle icon/chip in the composer toolbar. Its explanation opens as a popover and can be closed.
- Environment readiness appears only for blocking setup problems. Non-blocking Context Window advice stays in Setup Wizard and System Health.
- The result panel is a small closable toast outside the document flow. Successful results auto-hide.
- Dialogs and the diagnostics drawer close through the X button, backdrop click, or Escape.

## Changes and Patch review

The normal **Changes** tab is file-oriented:

- added/modified/deleted filters;
- task ownership for every file;
- readable line numbers and colored additions/removals;
- scope-expansion warning;
- clear distinction between auto-applied changes and an isolated patch awaiting approval.

The advanced **Patch review** is available from Technical Diagnostics:

- file selection before apply;
- split or unified view;
- approval state;
- selective apply to the original Project Path;
- raw patch data remains available without being the default experience.

## Reliability architecture

### Agent adapters

All providers implement a common capability and error contract:

```text
create/resume session
stream execution
cancel
read-only capability
file tool capability
error normalization
usage/capability metadata
```

Provider-specific text such as Qwen session or context errors is converted into typed controller errors.

### Model capability profiles

Profiles describe context size, recommended task size, structured-output reliability, prompt budget, and tool-calling ability:

- `small`: short prompts and small tasks;
- `normal`: standard local development;
- `strong`: larger cross-module tasks.

PromptBuilder compacts oversized prompts according to the selected model profile while retaining the goal, active task, latest validation, and recent failure evidence.

### Structured context handoff

When the model context cannot continue, the controller writes a compact JSON/Markdown handoff containing:

- goal and active task;
- completed tasks;
- accepted changed files;
- latest validation result;
- current typed failure;
- constraints and the next action.

A fresh session continues from this handoff instead of resending the entire conversation.

### Task checkpoints

Every accepted task can create a restorable project checkpoint. Checkpoints have file-size, total-size, and retention limits. A failed later task can restore the latest accepted task without discarding earlier work.

### Risk and approval

Risk is classified as low, medium, high, or critical. The result controls patch and approval defaults:

| Risk | Default behavior |
|---|---|
| Low | direct project edits, fully automatic |
| Medium | direct edits with task checkpoints |
| High | isolated review workspace and approval before apply |
| Critical | plan/patch only; no automatic apply |

Approval actions are available from Run Center and Patch review.

### Scope control

The final evidence reports files and features that may exceed the original request, such as unrequested README/example files or public API expansion. Scope warnings are review evidence; potentially destructive cleanup is never performed without a deterministic ownership rule or user approval.

## Validator plugins

V9 detects and normalizes validation for:

- Python/pytest;
- Maven and Gradle;
- .NET;
- Node;
- YAML and XML;
- SQL;
- Docker and Kubernetes;
- user-defined commands.

All validators return the same structured status, command, exit code, stdout/stderr summary, and evidence path.

## Release and migration

Version metadata is exposed through `/api/productization/version` and records:

- application version;
- database schema;
- workflow schema;
- configuration schema.

Read `UPGRADE.md`, `MIGRATIONS.md`, and `CHANGELOG.md` before upgrading an existing installation.

## Benchmark catalog

The built-in catalog includes ten deterministic scenarios:

```text
BENCH-001 single-file creation
BENCH-002 multi-file feature
BENCH-003 repair a failing test
BENCH-004 refactor without public API drift
BENCH-005 agent timeout recovery
BENCH-006 lost-session recovery
BENCH-007 context handoff
BENCH-008 controller restart
BENCH-009 project-lock conflict
BENCH-010 scope-expansion detection
```

Dry-run the catalog:

```bash
python scripts/run_productization_benchmarks.py
```

Real execution is explicit and never enabled by accident:

```bash
python scripts/run_productization_benchmarks.py --execute --real
```

## API additions

```text
GET  /api/productization/version
GET  /api/productization/upgrade-readiness
GET  /api/productization/model-profiles
GET  /api/productization/validators
POST /api/productization/validators/run
GET  /api/benchmarks/catalog
GET  /api/benchmarks/summary
```

## Test strategy

V9 tests cover capability profiles, risk, scope, structured handoff, task checkpoints, validators, adapters, releases, benchmark APIs, approval behavior, and the non-blocking UI contracts. Real Windows Qwen/OpenCode and browser tests remain opt-in because they require the user's local CLI/model/browser environment.
