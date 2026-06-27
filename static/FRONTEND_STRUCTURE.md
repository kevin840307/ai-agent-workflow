# Qwen Workflow Frontend Structure

This frontend keeps the existing DOM ids and API endpoints stable while splitting the UI code for easier maintenance.

```text
index.html                  # workflow runner page
workflow-designer.html      # custom workflow config / designer page
styles.css                  # stable CSS entry, imports css/*
app.js                      # compatibility module entry

css/
  tokens.css                # variables, reset, base controls
  layout.css                # app shell regions
  projects.css              # project sidebar
  header.css                # header and settings menu
  workflow-runner.css       # summary, chat, composer, details, artifacts
  workflow-designer.css     # custom workflow designer page
  modal.css                 # shared modal dialog
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
    modal.js
    requirements.js
    runs.js
    sessions.js
  pages/
    workflow-runner.js      # current page composition
    workflow-designer.js    # custom workflow designer UI with local draft data
```

## Stability rules

- Do not rename existing DOM ids unless backend/templates are updated together.
- Do not change existing API endpoints in feature files without backend changes.
- Add future pages under `js/pages/` and switch using `body data-page="..."`.
- Shared utilities belong under `js/core/`.
- Business/UI behavior belongs under `js/features/`.


## Workflow Designer MVP

The designer page is currently frontend-only and stores custom workflow drafts in `localStorage`. It is intended as a UI/schema prototype before backend APIs are added.

Supported UI concepts:

- Built-in system workflow is read-only and cannot be deleted.
- Users can duplicate the system workflow into an editable custom workflow.
- Custom workflows can add, delete, duplicate, and reorder steps.
- Each step has Basic, Prompt, Review, Retry, Gate, and Advanced settings.
- Review strategy supports current session, new agent, or multi-agent review concepts.
- Retry, timeout, expected files, Python validator, human gate, and interaction mode are represented in the UI.
- Export JSON shows the draft structure for backend schema design.
