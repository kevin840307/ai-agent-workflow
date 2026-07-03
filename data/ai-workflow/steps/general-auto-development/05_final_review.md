This step is executed by deterministic Python final review.

Expected behavior:
- Read `output/test-result.md`.
- Read `output/external-validation-result.md`.
- Write `output/final-review.md`.
- Return `Status: PASS` only when tests passed and external validation passed or was skipped by workflow setting.
- Do not ask the user questions.
