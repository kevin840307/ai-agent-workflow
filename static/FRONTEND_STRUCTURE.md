# Frontend Structure

The frontend is static HTML/CSS/JS served by FastAPI. It intentionally keeps DOM ids and API endpoints stable while feature code is split into small modules.

```text
index.html                  # workflow runner + chat page
workflow-designer.html      # workflow configuration page
styles.css                  # CSS entry, imports css/*
app.js                      # compatibility module entry

css/
  tokens.css
  layout.css
  projects.css
  header.css
  workflow-runner.css
  workflow-designer.css
  modal.css
  responsive.css

js/
  main.js                   # page router entry
  core/
    api.js                  # fetch wrapper
    context.js              # app context factory
    dom.js                  # DOM ids and helpers
    state.js                # shared runtime state
    storage.js              # UI-only preferences
  features/
    artifacts.js
    chat.js
    composer.js
    config.js
    console.js
    event-stream.js
    events.js
    interactions.js
    layout.js
    messages.js
    modal.js
    requirements.js
    runs.js
    sessions.js
    workflows.js
    workflow-notification.js
  pages/
    workflow-runner.js
    workflow-designer.js             # thin page entry facade
    workflow-designer-constants.js   # static select options and template presets
    workflow-designer/
      controller.js                  # page lifecycle, event delegation, API save/delete, orchestration
      layout-renderer.js             # overview, sidebar, step list, canvas, drag/drop rendering
      step-settings-renderer.js      # step settings tabs and form HTML
      template-editor.js             # step editor modal, prompt template editor, prompt preview
      import-export.js               # workflow JSON import/export UI and parsing
      function-catalog.js            # backend function metadata and prompt param catalog helpers
      model.js                       # workflow/step factories and normalization
      utils.js                       # DOM, escaping, option, clone, and toast helpers
```

## Runner Page

The runner supports two modes:

- Workflow: create runs, stream logs/status, retry/stop, inspect artifacts, answer questions, add guidance.
- Chat: normal project-session chat through the agent adapter.

Local storage is used only for UI preferences such as panel collapse state. Runtime data comes from backend APIs.

## Workflow Designer

Workflow Designer is API-backed. `js/pages/workflow-designer.js` is intentionally a thin entry facade so the public page import stays stable while implementation code lives under `js/pages/workflow-designer/`.

Module responsibilities:

- `controller.js`: owns page lifecycle, event delegation, state transitions, API persistence, and module wiring. It should stay orchestration-only.
- `layout-renderer.js`: owns top-level designer rendering, sidebar/workflow labels, step list, canvas, filters, density controls, context menu, and drag/drop.
- `step-settings-renderer.js`: owns step settings tab rendering, including basic/prompt/review/retry/gate/advanced/consensus forms.
- `template-editor.js`: owns the step editor modal, prompt template editor, template diagnostics, prompt preview, and template preset loading.
- `import-export.js`: owns workflow JSON import validation, imported workflow normalization, export JSON rendering, and import/export overlays.
- `function-catalog.js`: owns backend function metadata display helpers and prompt parameter catalog merging.
- `model.js`: owns workflow/step creation, default values, normalization, and filename/template defaults.
- `utils.js`: owns shared DOM helpers, escaping, option rendering, cloning, ids, and toast UI.
- `workflow-designer-constants.js`: owns static option lists and prompt template presets.

Size guardrails:

- `workflow-designer.js` should stay a thin entry facade.
- `controller.js` should stay below 1,200 lines and should not absorb renderer/editor/import logic again.
- Focused designer modules should stay below 700 lines each.

Workflow Designer is API-backed.

- `GET /api/workflows` loads system and custom workflows plus backend function metadata.
- `PUT /api/workflows/{id}` saves custom workflows.
- `DELETE /api/workflows/{id}` deletes custom workflows.
- System workflow is read-only and cannot be deleted.
- Prompt template content is loaded from and saved to the workflow bundle folder.

The designer supports step settings for:

- Basic type/output/validator/agent settings
- Prompt template editing
- Sources and skill paths
- Review strategy and aggregation
- Retry target/count and failure feedback
- Human gate and interaction settings
- Timeout and expected files
- Consensus agent settings

## Stability Rules

- Do not rename existing DOM ids unless HTML and JS are updated together.
- Do not change existing API endpoints without backend controller/service changes.
- Keep localStorage limited to UI preference state.
- Runtime state should come from backend APIs and event streams.
- Add new pages under `js/pages/`.
- Shared utilities belong under `js/core/`.
- Business/UI behavior belongs under `js/features/`.
