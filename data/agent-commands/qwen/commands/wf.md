---
description: Run a saved AI Workflow through the local Workflow Controller
---

Run the saved workflow from the current project directory. The controller owns planning, retry, validation, checkpoints, and final completion checks.

Arguments:
{{args}}

Execute the workflow and return the run id, session id, final status, and any structured failure details:

!{@@AIWF_PYTHON@@ @@AIWF_LAUNCHER@@ /wf {{args}} --wait}
