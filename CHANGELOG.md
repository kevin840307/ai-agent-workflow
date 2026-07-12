# Changelog

## 1.11.1 — V24.1 Security Scan hotfix

- Fixed Windows `NotImplementedError` before Workflow Step 1 by routing validator subprocesses through the cross-platform `CommandRunner`.
- Marked Security Vulnerability Scan as a report-only Workflow that does not establish an unrelated project Build/Test baseline before scanning.
- Persisted the Workflow-level `validationBaseline` policy into each Run for restart-safe execution.
- Reconciled Run state whenever the browser event stream opens, so very fast terminal failures are shown immediately instead of appearing idle.
- Added Security Scan baseline-policy, validator runner, timeout mapping, fast-terminal UI, and direct-subprocess regression tests.

## 1.11.0 — V24

- Added ordered transactional SQLite migrations with automatic pre-upgrade backup, checksum audit, rollback, and newer-schema rejection.
- Expanded explicit `RuntimeContext` adoption while retaining the compatibility Runtime Facade.
- Added the unified cross-platform `CommandRunner` and stable developer/commit/release/e2e test profiles.
- Completed Release allowlist checks for Agent slash-command templates and Workflow Contract Schema.

## 1.10.0 — V23

- Added split runtime, development, and browser dependency files; added PyYAML as a required runtime package.
- Added tested-version constraints and isolated FastAPI startup smoke.
- Added allowlisted deterministic Release ZIP generation with per-file SHA-256 manifest.
- Added code-first `aiwf.failure.v3` while preserving V2 compatibility fields.
- Added explicit `RuntimeContext` and migrated application lifecycle ownership in `app/main.py`.
- Extracted failed-step recovery from the main Executor loop and Agent tool-call parsing from `AgentStepRunner`.
- Added V23 release/failure/runtime tests and updated English/Traditional Chinese documentation.

## 1.9.0 — V22

- Repaired persisted Artifact metadata and previews.
- Restored Step-scoped related-file dialogs.
- Corrected Split Diff geometry and Patch scope exclusions.

## 1.8.x — V20/V21

- Added unattended transaction safety, Patch approval evidence binding, Partial Patch revalidation, and large Artifact/Diff segmentation.
