---
description: Run a saved AI Workflow through the local Qwen Workflow Web backend
---

Run the local workflow runner with the saved workflow arguments below. Use this when the user wants the web project's controlled workflow loop, validation, retry, and artifacts instead of only the current OpenCode chat.

Arguments:
$ARGUMENTS

Execute the workflow and then summarize the run id, session id, status, and any failure output:

!`python -m app.cli.aiwf /wf $ARGUMENTS --wait`
