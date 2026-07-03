This step is executed by deterministic Python review.

Expected behavior:
- Validate that `todo.md` has `Status: READY`.
- Validate that task IDs and acceptance criteria exist.
- Validate that the external validation stage is present and can skip when no script is configured or found.
- Write `output/implementation-review.md` with `Status: PASS` when the TODO is valid.
- Do not ask the user questions.
