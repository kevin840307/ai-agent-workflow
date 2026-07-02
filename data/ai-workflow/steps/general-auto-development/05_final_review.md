This is now a deterministic Python function step.

The workflow function `validate_general_auto_final` reads:
- `output/build-result.md`
- `output/test-result.md`
- `output/external-validation-result.md`

It writes `output/final-review.md` with `Status: PASS` only when build output exists, automated tests pass, and the mandatory external validation script passes.
