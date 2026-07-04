This step is executed by deterministic Python final review.

Expected behavior:
- Read `output/task-manifest.md`.
- Read `output/test-result.md`.
- Read `output/external-validation-result.md`.
- Write `output/final-review.md`.
- Write `output/verifier-report.json` with machine-readable PASS/FAIL evidence.
- Write `output/diff-context.md` for the diff-only reviewer.
- Return `Status: PASS` only when tests passed and external validation passed or was skipped by workflow setting.
- Do not ask the user questions.
