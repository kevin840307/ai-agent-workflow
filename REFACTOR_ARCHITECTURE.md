# Refactor Architecture Plan

This document defines the target backend/frontend architecture for the next refactor. The goal is to make the app easier to extend with more workflows and agent providers, while safely removing old compatibility files and unused folders.

## Goals

- Keep workflow execution stable while reducing cross-module coupling.
- Make agent providers plug-in friendly: Qwen, OpenCode, and future providers should share the same contract.
- Make workflow functions easy to add without editing large central files.
- Make frontend pages easier to maintain by separating state, API, rendering, and actions.
- Remove unused compatibility files only after tests prove they are no longer referenced.
- Keep runtime data such as `data/store.json` and project workspaces out of architecture assumptions.

## Non-Goals

- Do not rewrite the app into a bundled frontend framework yet.
- Do not introduce a database yet; keep JSON store but isolate the persistence interface.
- Do not remove existing API routes or DOM ids until UI tests and manual usage are updated.
- Do not remove backward-compatible facades in the same patch that moves implementation code.

## Current Pain Points

- Backend has multiple facade/compatibility modules:
  - `app/runtime_modules/api.py` re-exports many runtime objects.
  - `app/workflow_functions.py` is a compatibility facade for workflow functions.
  - `app/runtime_modules/qwen.py` is Qwen-specific but still used by tests and serve code.
- `project_service.py` and `workflow_service.py` still combine API use-case logic, store orchestration, and runtime decisions.
- Workflow persistence, run state, logs, events, and artifacts are split but still accessed through broad runtime facades.
- Frontend runner is feature-split, but many features still share one mutable context object.
- Workflow Designer is split into modules, but `controller.js` remains the orchestration hotspot.
- Obsolete files removed in the first refactor pass:
  - `static/app.js`
  - `README_PATCH.md`
  - `README_CONTEXT_PATCH.md`
  - `README_PROMPT_TEMPLATE_PATCH.md`

## Target Backend Structure

```text
app/
  main.py
  api/
    routes/
      artifacts.py
      config.py
      health.py
      maintenance.py
      projects.py
      workflow_runs.py
      workflows.py
    errors.py
    dependencies.py
  core/
    paths.py
    settings.py
    metrics.py
    locks.py
    time.py
  persistence/
    json_store.py
    repositories/
      sessions.py
      messages.py
      runs.py
      workflows.py
  domain/
    schemas.py
    models.py
    workflow_definition.py
    run_state.py
  services/
    chat_service.py
    project_service.py
    workflow_run_service.py
    workflow_config_service.py
    artifact_service.py
    maintenance_service.py
  workflow/
    executor.py
    actions.py
    retry_policy.py
    prompt_builder.py
    questions.py
    step_config.py
    step_utils.py
    functions/
      __init__.py
      registry.py
      catalog.py
      core.py
      security/
        context.py
        candidates.py
        report.py
        validation.py
    agents/
      manager.py
      base.py
      providers/
        qwen.py
        qwen_serve.py
        opencode.py
  testing/
    mock_agent.py
```

## Backend Layer Rules

- `api/routes/*` only maps HTTP requests to services.
- `services/*` owns use cases and transactions; it should not know CLI command details.
- `persistence/*` owns JSON store reads/writes and repository queries.
- `workflow/*` owns execution mechanics, prompt rendering, retries, and Python functions.
- `workflow/agents/*` owns provider-specific agent behavior.
- `core/*` owns process-wide primitives such as paths, locks, metrics, and app settings.
- Compatibility imports should live in a small `app/compat/` package during migration, then be removed.

## Backend Migration Plan

1. Create new packages without moving behavior:
   - `app/api/routes`
   - `app/core`
   - `app/persistence`
   - `app/workflow`
   - `app/workflow/agents`
2. Move low-risk runtime primitives first:
   - `runtime_modules/paths.py` -> `core/paths.py`
   - `runtime_modules/locks.py` -> `core/locks.py`
   - `runtime_modules/metrics.py` -> `core/metrics.py`
   - `runtime_modules/api_errors.py` -> `api/errors.py`
3. Move store code behind repository interfaces:
   - `runtime_modules/store.py` -> `persistence/json_store.py`
   - `repositories/store_repository.py` -> focused repositories.
4. Split services:
   - `project_service.chat` -> `chat_service.py`
   - workflow run create/retry/terminate -> `workflow_run_service.py`
   - project CRUD remains in `project_service.py`.
5. Move workflow runtime:
   - `workflow_runtime/*` -> `workflow/*`
   - `workflow_runtime/agent_adapters/*` -> `workflow/agents/providers/*` (facades deleted after internal imports were removed)
6. Move workflow functions:
   - keep `app/workflow_functions.py` as a temporary facade.
   - make `workflow/functions/registry.py` the only implementation registry.
   - make `workflow/functions/catalog.py` the only UI metadata source.
7. Add compatibility tests for old imports, then remove old imports when no internal code uses them.
8. Remove compatibility modules only after two commits:
   - commit 1: move implementation and keep facades.
   - commit 2: update all internal imports and delete facades.

## Target Frontend Structure

```text
static/
  index.html
  workflow-designer.html
  styles.css
  css/
    base/
      tokens.css
      layout.css
      responsive.css
    components/
      buttons.css
      modal.css
      sidebar.css
      tabs.css
    pages/
      runner.css
      designer.css
  js/
    app.js
    core/
      api-client.js
      event-bus.js
      dom.js
      storage.js
      state-store.js
    shared/
      sidebar.js
      modal.js
      markdown.js
      artifact-viewer.js
    runner/
      index.js
      runner-state.js
      runner-api.js
      runner-renderer.js
      runner-actions.js
      features/
        chat.js
        workflow-runs.js
        artifacts.js
        sessions.js
        composer.js
        interactions.js
    designer/
      index.js
      designer-state.js
      designer-api.js
      designer-renderer.js
      designer-actions.js
      model.js
      function-catalog.js
      template-editor.js
      import-export.js
      step-settings/
        basic.js
        prompt.js
        review.js
        retry.js
        gate.js
        advanced.js
```

## Frontend Layer Rules

- `core/*` must not know runner/designer-specific DOM ids.
- `shared/*` contains reusable UI widgets used by both pages.
- `runner/*` owns workflow execution and chat UX.
- `designer/*` owns workflow config editing.
- Each page should have four clear seams:
  - `*-state.js`: state shape and reducers/mutations.
  - `*-api.js`: backend calls.
  - `*-renderer.js`: DOM rendering.
  - `*-actions.js`: user actions and orchestration.
- Renderers should not call `fetch`.
- API modules should not touch DOM.
- Event handlers should call actions, not mutate DOM directly.

## Frontend Migration Plan

1. Rename current `static/js/main.js` to the new page router shape, but keep the URL and script entry stable.
2. Move `static/js/components/sidebar.js` to `static/js/shared/sidebar.js`.
3. Split runner features into `runner/` while preserving exported factory names until callers move.
4. Split Workflow Designer `controller.js`:
   - API code -> `designer-api.js`
   - action handlers -> `designer-actions.js`
   - state read/write -> `designer-state.js`
   - top-level render wiring -> `designer-renderer.js`
5. Split `step-settings-renderer.js` by tab after behavior is covered:
   - basic, prompt, review, retry, gate, advanced.
6. Move CSS into `base`, `components`, and `pages` groups.
7. Delete old files only when `rg` shows no references and static syntax tests pass.

## Files And Folders To Audit For Removal

These are removal candidates, not approved deletions yet.

| Path | Current suspicion | Required proof before deletion |
| --- | --- | --- |
| `static/app.js` | Removed. Old compatibility entry; current HTML uses `static/js/main.js`. | Browser/static smoke must keep passing. |
| `README_PATCH.md` | Removed. Patch-era note. | README/architecture docs carry current guidance. |
| `README_CONTEXT_PATCH.md` | Removed. Patch-era note. | README/architecture docs carry current guidance. |
| `README_PROMPT_TEMPLATE_PATCH.md` | Removed. Patch-era note. | Prompt template behavior is covered by workflow docs/tests. |
| `workspaces/` contents | Runtime output, not source. | Confirm no checked-in required fixture lives there. |
| old compatibility facades | Needed during migration. | Internal imports removed and compatibility tests updated. |

Do not delete:

- `data/ai-workflow/workflows/*`: canonical workflow manifests.
- `data/ai-workflow/steps/*`: separated skill/prompt markdown.
- `data/ai-workflow/contracts/*`: separated step metadata.
- `data/ai-workflow/validators/*` and `data/ai-workflow/tools/*`: Python workflow assets.
- `data/settings.json`: local settings.
- `data/store.json`: local runtime state; consider adding a sample file instead of deleting user state.

## API Boundaries To Preserve

- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{id}/messages`
- `POST /api/sessions/{id}/messages`
- `POST /api/sessions/{id}/workflow-runs`
- `GET /api/sessions/{id}/workflow-runs/latest`
- `GET /api/workflow-runs/{id}`
- `POST /api/workflow-runs/{id}/retry`
- `POST /api/workflow-runs/{id}/terminate`
- `GET /api/workflows`
- `PUT /api/workflows/{id}`
- `DELETE /api/workflows/{id}`
- `GET /api/workflows/functions`
- `GET /health`
- `GET /ready`
- `GET /metrics`

Any rename should add a compatibility route first.

## Test Strategy

Run after each migration step:

```powershell
python -m compileall app tests
python -m unittest discover -s tests -v
Get-Content -Raw static\js\main.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-runner.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\controller.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\layout-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\step-settings-renderer.js | node --input-type=module --check
Get-Content -Raw static\js\pages\workflow-designer\template-editor.js | node --input-type=module --check
```

Add or keep tests for:

- store atomic write and Windows replace retry
- one active workflow run per project
- chat idempotency and busy-session behavior
- workflow retry target behavior
- artifact path traversal rejection
- workflow function registry/catalog consistency
- frontend static module version consistency
- Workflow Designer module size guardrails

## Refactor Sequence

Recommended order:

1. Backend core extraction: paths, locks, metrics, errors.
2. Persistence extraction: JSON store and repositories.
3. Workflow run service split.
4. Agent provider package cleanup.
5. Workflow function registry/catalog cleanup.
6. Frontend shared/core cleanup.
7. Runner page split.
8. Designer controller split.
9. CSS grouping.
10. Remove audited obsolete files.

This order keeps the riskiest UI moves after backend safety is stable.

## Done Criteria

- All tests pass.
- Frontend syntax checks pass.
- `rg` confirms deleted files have no references.
- `git diff --check` passes.
- No new runtime state files are committed by accident.
- `ARCHITECTURE.md` and `static/FRONTEND_STRUCTURE.md` are updated or replaced by this document.
- Manual smoke:
  - create project
  - run workflow
  - retry failed step
  - stop active run
  - chat with selected agent
  - open Workflow Designer
  - edit custom workflow prompt
  - save and reload
