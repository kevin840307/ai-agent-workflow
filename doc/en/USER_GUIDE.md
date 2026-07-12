# User Guide

## Simple Mode

Simple Mode is the default for normal users and is unattended by default.

```text
Choose project → enter one requirement → start
→ platform discovers, edits, validates, repairs, and recovers
→ inspect one readable result
```

The primary screen shows:

- current Autopilot phase;
- completed/active tasks;
- whether the model is online, offline/retrying, or awaiting confirmation;
- a compact final summary;
- direct access to the Patch Review workbench and Validation Evidence.

It does not require normal users to understand session IDs, retry fingerprints, task manifests, provider queues, or raw events.


### Patch Review and Execution Artifacts

- Run Center no longer has a standalone Changes tab. Overview shows the change summary and opens the single Patch Review workbench.
- The workbench provides file search/filter, a resizable/collapsible sidebar whose state is remembered, Unified/Split views, focus mode, font zoom, independent scrolling, and bounded load-more rendering for large Diffs.
- Reject-and-repair, approve-only, and approve-and-apply are separate actions. Approval is bound to Patch, file selection, and Validation Evidence hashes and becomes stale when any evidence changes.
- A Partial Patch is rebuilt and revalidated in an isolated workspace; unattended delivery accepts only the complete Patch.
- Technical Files is renamed Execution Artifacts. Type, importance, order, producer, media type, and preview mode come only from explicit metadata/contracts. Legacy Runs are repaired once on first access; records still lacking metadata remain Unclassified.
- A Step's related-file action opens a dedicated Step-scoped dialog containing only that Step's prompt, explicit outputs, dependencies, and evidence. It does not navigate to the global Execution Artifacts list.

## Advanced Mode

Advanced Mode exposes workflow/profile/thinking selection, unattended toggle, Project Validation Profile editing, Validation Script, sessions, checkpoints, retry history, artifacts, Patch Review, Repair Strategy, and Run comparison.

Simple and Advanced Mode use the same run state and workflow kernel. Switching display mode does not create a second execution path.

## Project Validation Profile

The profile is controller-owned and reusable per Project Path. It contains detected or confirmed validation phases, baseline/fast/full categories, environment requirements, artifacts, and optional scope policy.

Profile states:

| State | Meaning |
|---|---|
| `Draft` | detected or edited, not yet proven |
| `Verified` | successfully executed at least once |
| `Trusted` | successfully verified at least three times |
| `Stale` | build/test/validation descriptors changed |

Changing a profile returns it to Draft. A Stale profile must be re-verified before unattended delivery.

## Unattended flow

```text
Discover project
→ environment preflight
→ baseline validation
→ task contracts
→ checkpoint / isolated workspace
→ Agent implementation
→ focused validation
→ progress-aware repair
→ full validation and immutable Validation Script
→ atomic apply and post-apply validation
```

If the controller restarts, unattended interrupted runs are detected and resumed from persisted state when recovery is safe. If the model endpoint goes offline, the run waits with low-frequency probes and continues when the endpoint returns rather than consuming retry attempts rapidly.

## UI workspaces

- **Overview**: the Run Center uses its full available width for readable progress, current action, steps, change summary, and the Patch Review entry.
- **Patch Review workbench**: a near-fullscreen surface with a remembered resizable/collapsible file list, independently scrollable and bounded Diff, Unified/Split views, focus mode, evidence-bound approval, and Partial Patch revalidation.
- **Validation**: profile, baseline, executed command, exit code, duration, required/blocking state, Build/Test/Lint/Type Check, external validation, and related Evidence.
- **Technical Diagnostics**: a closable/maximizable full-height drawer for Agent raw output, complete logs, Execution Artifacts, Repair Strategy, events, process/session information, Delivery/Rollback evidence, and repair tools. It does not duplicate normal Patch Review.

Workflow and Chat modes both keep execution mode, Options, and the composer visible. A step's `...` menu lists its Prompt, Output, Feedback, and files; selecting one opens the large Markdown dialog with Source/Preview, Copy, Download, and Diagnostics actions.

Tabs keep a fixed height. Large logs are batched and capped for rendering so they do not freeze the UI. The platform does not auto-switch the tab currently being inspected.

Stopping a run produces one cancellation state. Cancelled runs do not open a second overlapping result dialog.

## Workflow choice

### General Auto Development

Best default for local/small models:

```text
AI plan → read-only implementation review → task loop → test generation
→ focused validation → full engineering validation → final review
→ immutable external validation → deterministic completion gate
```

### Adaptive Auto Workflow

Best for broader work with a stronger model. Replanning is reserved for true specification conflicts; test, validation, session, context, no-file-change, transport, and scope failures route to the smallest owning repair action.

### Security Vulnerability Scan

Read-mostly inventory and supported security checks. It must not create product code.

## Completion rules

A model saying “done” is not completion. Delivery requires:

- actual Agent-created changes;
- no protected-path or task-scope violation;
- no new regression compared with baseline;
- reusable Project Validation Profile gates passed;
- required immutable Validation Script passed;
- source conflict checks and atomic delivery passed.

The controller never turns model FILE blocks or tool-call JSON into requested source code.

## Large execution details in V19

The Overview tab owns the vertical scroll for the execution-step list and selected-step summary. Use **Expand details** to open one large Step dialog when complete evidence is needed. The dialog has one scrollable body and can be closed with its close button, the backdrop, or Escape.

In Technical Diagnostics:

- Technical files and artifact content use the section's single scrollbar.
- Apply to Project is placed next to Split/Unified Patch controls.
- The Patch Review file navigator and code preview scroll independently; Split headers and rows use one exact 50/50 grid. Tool/controller metadata directories are excluded from Patch scope while project-local `.qwen` and `.opencode` remain available in the Agent cwd. Validation, Patch Review, and Repair Strategy manage scrolling within their respective workspaces. Large Diffs and Artifact previews load in bounded segments.
- Agent output and Logs use a bounded display window so long unattended Runs do not continuously enlarge the browser DOM.
