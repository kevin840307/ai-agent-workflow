# Final Completion Gate / Report

This deterministic Python gate decides whether the run may become `COMPLETED`.

Required conditions:
- `output/final-review.md` contains `Status: PASS`.
- All required tasks are accepted.
- Required user validation has immutable execution evidence with exit code 0.
- Optional validation may be `NOT_CONFIGURED`; it must never be represented as a fake PASS.
- Required tests and validators have successful execution evidence.
- No unresolved failed/blocked step, policy violation, scope decision, or checkpoint inconsistency remains.

This step does not generate code, repair files, or replace Qwen/OpenCode behavior.
