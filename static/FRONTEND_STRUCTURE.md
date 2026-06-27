# Qwen Workflow Frontend Structure

This frontend keeps the existing DOM ids and API endpoints stable while splitting the UI code for easier maintenance.

```text
index.html
styles.css                  # stable CSS entry, imports css/*
app.js                      # compatibility module entry

css/
  tokens.css                # variables, reset, base controls
  layout.css                # app shell regions
  projects.css              # project sidebar
  header.css                # header and settings menu
  workflow-runner.css       # summary, chat, composer, details, artifacts
  responsive.css            # collapsed states and responsive rules

js/
  main.js                   # page router entry
  core/
    api.js                  # fetch wrapper
    context.js              # app context factory
    dom.js                  # DOM ids and helpers
    state.js                # shared runtime state and workflow steps
  features/
    artifacts.js
    composer.js
    config.js
    console.js
    event-stream.js
    events.js
    interactions.js
    layout.js
    messages.js
    requirements.js
    runs.js
    sessions.js
  pages/
    workflow-runner.js      # current page composition
    workflow-designer.js    # future custom workflow page hook
```

## Stability rules

- Do not rename existing DOM ids unless backend/templates are updated together.
- Do not change existing API endpoints in feature files without backend changes.
- Add future pages under `js/pages/` and switch using `body data-page="..."`.
- Shared utilities belong under `js/core/`.
- Business/UI behavior belongs under `js/features/`.
