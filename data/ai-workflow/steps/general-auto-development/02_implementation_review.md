This is now a deterministic Python function step.

The workflow function `validate_general_auto_plan` validates `output/todo.md` and writes `output/implementation-review.md`.

Expected behavior:
- Do not call an AI agent.
- Require `Status: READY`, `TASK-001` style task ids, acceptance criteria, automated test coverage, and mandatory external validation.
- On failure, retry from Plan Tasks with the concrete validation error.
