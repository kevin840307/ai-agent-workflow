This step is executed by deterministic Python review.

Expected behavior:
- Validate that `todo.md` has `Status: READY`.
- Validate that task IDs and acceptance criteria exist.
- Validate that the external validation stage is present and can skip when no script is configured or found.
- Validate that named deliverables from the requirement are not collapsed into one vague task.
- Validate that each build-owned task has task-specific acceptance criteria instead of only generic final-result wording.
- Write `output/implementation-review.md` with `Status: PASS` when the TODO is valid.
- Write `output/task-manifest.json`, `output/generated-workflow-instance.json`, `output/workflow-instance-validation.md`, and `output/workflow-run-trace.md`.
- Do not ask the user questions.
