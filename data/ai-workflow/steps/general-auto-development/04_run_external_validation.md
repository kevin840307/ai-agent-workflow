This is a Python function step.

It runs the project validation script for this run when one is configured or present.

Run-specific validation script:
{{validation_script}}

If the run-specific validation script is empty, fallback script names are used in priority order:
- `validation.py`
- `validate.py`
- `verify.py`
- `check.py`

This step passes with a skipped result if no validation script is configured or found.
This step must fail if the validation script exits with a non-zero status.
When this step fails, the workflow retries from Build with the full validation output as feedback.
