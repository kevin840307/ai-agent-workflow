# Hardening Next

This change set focuses on system stability rather than model quality.

## 1. Store Abstraction

New file-backed interfaces provide a seam for replacing JSON files with SQLite/PostgreSQL later:

- `app/stores/run_store.py`
- `app/stores/step_store.py`
- `app/stores/artifact_store.py`
- `app/stores/lock_store.py`

The current backend still uses the existing JSON store, but workflow services can now read runs, steps, artifacts, and locks through stable interfaces.

## 2. Runtime Architecture

`actions.py` is intentionally not moved wholesale. The safer approach is gradual extraction behind tests. This round adds store seams and keeps previous `actions_registry.py` dispatch extraction intact.

## 3. Browser UI Smoke Test

`scripts/run_browser_ui_smoke.py` supports two modes:

- default static smoke check for CI without browsers;
- optional Playwright browser mode with `RUN_PLAYWRIGHT_UI=1`.

Checks cover Advanced/Detail labels, long-content layout hardening, and core Run Detail wiring.

## 4. Lifecycle Stress Coverage

`tests/test_hardening_next.py` adds stress-style unit coverage for:

- live active-run detection;
- dead-owner recovery;
- idempotent cancel requests;
- stale project lock cleanup.

## 5. Artifact Cleanup / Retention

`POST /api/maintenance/cleanup` now supports:

- `keep_per_project`
- `older_than_days`
- `dry_run`
- `include_orphan_workspaces`

Cleanup never removes active runs and only deletes safe workflow run directories.
