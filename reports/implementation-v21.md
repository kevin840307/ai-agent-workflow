# V21 Patch Review, Validation Evidence, and Execution Artifacts Implementation Report

## Scope

V21 implements the requested Run Center, Validation, Patch Review, Diff, Execution Artifact, and semantic-hardcode improvements on top of the V20 unattended reliability foundation. OS-level Agent sandboxing remains deliberately excluded.

## Non-negotiable runtime rules preserved

1. Qwen/OpenCode remains responsible for creating or editing requested project source and test files. The Controller only orchestrates, validates, records evidence, and delivers reviewed Agent changes.
2. Agent cwd is the effective Project Path. In isolated delivery this is the isolated project copy, including project-local `.qwen` and `.opencode` configuration.
3. Same-project active writes remain serialized. Different projects and distinct Workflow/Agent sessions may execute concurrently through bounded provider slots.
4. Free-form requirement, filename, path, Step title, focused file, and rejection comment are not used to infer intent, risk, phase, validation role, Artifact role, or repair target.
5. Unattended Partial Apply remains prohibited. A Partial Patch is available only in attended review mode and must be reconstructed and revalidated before approval or apply.

## Run Center information architecture

- Removed the standalone Changes tab.
- Run Center now contains only **Overview** and **Validation**.
- Overview presents concise change and validation summaries and opens the single authoritative Patch Review workbench.
- Technical Diagnostics no longer contains a duplicate Patch Review surface.

## Validation Evidence Center

Validation cards now expose explicit evidence rather than only a status label:

- executed command;
- exit code;
- duration;
- passed/failed/skipped counts when available;
- Required and Blocks Apply flags;
- Baseline state;
- Retry information;
- producer Step and related Artifact actions.

Skipped, missing, non-executed, draft, or stale validation evidence cannot authorize unattended apply.

## Patch Review workbench

The workbench is a near-fullscreen, single-source review surface with:

- searchable/filterable changed-file list;
- resizable and collapsible file sidebar whose width/collapse state is remembered;
- Unified and Split views with remembered preference;
- focus mode and font zoom;
- independent file-list and Diff scrolling;
- keyboard navigation (`F`, `J/K`, `N/P`, `Esc`);
- bounded large-Diff rendering: 1,500 rows per segment plus browser `content-visibility` virtualization;
- explicit Reject and Repair, Approve Only, and Approve and Apply actions;
- fixed decision footer with selection, validation, and approval state.

The real Chromium geometry at 1920×1080 is 1904×1064; the Diff content width is 1622px with a 280px sidebar.

## Evidence-bound approval

Approval is no longer a Boolean. It is bound to:

- Patch Hash;
- exact selected-file list;
- Selection Hash;
- per-file content hashes;
- exact Validation Evidence Hash;
- Run/approval metadata.

Any Patch, selection, or evidence change makes the existing approval stale. Re-running a Partial Patch validation creates new evidence and invalidates an older approval even when both validation runs pass.

## Partial Patch safety

For an attended Partial Patch:

1. Build the selected combination in an isolated project copy.
2. Run all Required validation against that exact combination.
3. Persist a selection-scoped validation record and Evidence Hash.
4. Bind approval to that exact evidence.
5. Recheck Patch, Selection, and Evidence hashes immediately before apply.

A full-Patch validation result cannot be reused for a subset.

## Structured rejection

Reject and Repair submits explicit fields:

- reason code;
- original user comment;
- explicitly selected retry Step or no automatic retry;
- Patch and validation evidence references.

The Controller does not infer the repair target from filenames, selected files, Step labels, or comment text.

## Execution Artifacts

“Technical Files” is replaced by a shared **Execution Artifacts** master-detail viewer used from Step, Validation, and Diagnostics entry points.

Artifact presentation is contract-driven through:

- `category`;
- `role`;
- `visibility`;
- `displayName` / `displayOrder`;
- `producerStepKey`;
- `mediaType`;
- `size` / `contentHash`.

Unknown legacy Artifacts remain **Unclassified**. They are not guessed from filename or path. The viewer supports Markdown, JSON, log, and raw presentation, segmented 500,000-character loading, download/copy, producer-Step navigation, and total/diagnostic storage plus latest archive summary.

Diagnostic archive is a maintenance action. Original files remain unless an explicit prune policy is enabled.

## Resource and code minimization

- One Patch Review module replaces three overlapping change/Diff/review surfaces.
- One shared Artifact Viewer replaces separate Step-file and diagnostics viewers.
- Large content is incrementally rendered rather than fully materialized in the DOM.
- Preferences use existing local storage infrastructure.
- Existing V20 Delivery Journal, Lease/Fencing, SQLite, process supervision, and isolated workspace mechanisms are reused rather than duplicated.

## Real Qwen E2E package

The opt-in runner includes:

1. existing Python defect repair;
2. multi-file feature generation;
3. project-local Agent configuration and effective cwd verification;
4. validation-driven repair loop;
5. concurrent different-project/different-session runs with distinct Workflow and Qwen CLI session IDs.

Run locally:

```powershell
python scripts/run_real_qwen_unattended_e2e.py
python scripts/run_real_qwen_unattended_e2e.py --parallel
```

The runner forces real Qwen mode and rejects a missing CLI. Actual model execution was not performed in this environment and is not represented as passed.

## Deliberate exclusion

OS-level Agent sandboxing is not implemented. Existing isolated workspace, project-path guards, process supervision, environment filtering, evidence gates, and atomic delivery are defense-in-depth controls, not an OS security boundary.
