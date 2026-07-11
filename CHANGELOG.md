# Changelog

## 1.1.0 — Stability V11

- Fixed Generate Tests ownership for pytest files that already existed at the project root while keeping new tests under `tests/`.
- Fixed same-object Store synchronization during retry reset and final completion so Run state cannot erase its own `workspace` or `steps`.
- Moved restart recovery into one compact Current Action notice and removed the repeated large failure panel.
- Deduplicated Windows path aliases in Changes and removed repeated `+/-` statistics from the preview header.
- Added stable absolute-path launchers for Qwen Code/OpenCode interactive `/wf` and `/wstep`.
- Added cross-directory slash-command dry-run verification to installation and Production Acceptance.
- Added Stability V11 regression tests and registered all 49 test modules in the isolated matrix.

## 1.0.0 — Production Readiness V10

- Added immutable required user-validation contracts and atomic Completion Gate.
- Added task-scoped checkpoint rollback, current-state filesystem handoff, and fresh-session recovery after rollback/timeout/context restore.
- Fixed pytest parametrization, builtin fixture, and `conftest.py` fixture classification; test-definition failures now retry only test generation.
- Fixed retry/store synchronization so repaired Steps cannot remain failed in stale memory and block final completion.
- Made Production Acceptance execute each test module in an isolated pytest interpreter with JUnit evidence.
- Exposed and physically retained only Adaptive Auto Workflow, General Auto Development, and Security Vulnerability Scan.
- Rebuilt Change Preview and Patch Review as single-layer, file-first, dismissible interfaces with exact added/removed counts.
- Made optional validation `NOT_CONFIGURED`, required validation non-skippable, and validation files protected by SHA-256.

## 0.9.0 — Productization V9

- Added model capability profiles and prompt budgets.
- Added structured context handoff and task-level checkpoints.
- Added risk-aware patch/approval policies and scope-delta evidence.
- Added validator plugins for Python, Java, .NET, Node, YAML, XML, SQL, Docker, Kubernetes, and custom commands.
- Added fixed benchmark catalog and live benchmark runner.
- Added release/schema version manifest and upgrade readiness API.
- Reworked runner UI into compact notices, non-blocking result dock, readable timeline, file-first Changes, and selective Patch review.

## 1.1.0 - Focused Change Review and Local Qwen Cases

- Replaced the bottom/right result dock with one dismissible center result dialog.
- Changed the Run Center Changes tab to a stacked file navigator and one authoritative diff preview.
- Added independent vertical and horizontal scrolling for unified and split Patch views.
- Expanded Patch Review only inside the advanced diagnostics drawer.
- Added six real Qwen/OpenCode local cases with one-line prompts and required `validation.py` evidence.
- Added Windows and Python runners that produce per-case and aggregate reports.
