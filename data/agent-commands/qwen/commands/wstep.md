---
description: Run one ad-hoc AI Workflow step with a skill/slash command and contract
---

Run one local workflow step through the Qwen Workflow Web backend. Use this for quick skill + config runs such as `steps/build.md build.yaml "requirement"`, or for agent slash-command + config runs such as `/build build.yaml "requirement"`.

Arguments:
{{args}}

Execute the workflow step and then summarize the run id, session id, status, and any failure output:

!{python -m app.cli.aiwf /wstep {{args}} --wait}
