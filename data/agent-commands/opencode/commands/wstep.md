---
description: Run one controlled workflow step with a skill/slash command and contract
---

Run one ad-hoc step from the current project directory. Examples: `steps/build.md build.yaml "requirement"` or `/build build.yaml "requirement"`.

Arguments:
$ARGUMENTS

Execute the step and return the run id, session id, final status, and any structured failure details:

!`@@AIWF_PYTHON@@ @@AIWF_LAUNCHER@@ /wstep $ARGUMENTS --wait`
