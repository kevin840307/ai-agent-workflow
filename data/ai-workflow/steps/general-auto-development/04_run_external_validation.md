This is a Python function step.

It runs the mandatory project validation script for this run.

Run-specific validation script:
{{validation_script}}

If the run-specific validation script is empty, fallback script names are used in priority order:
- `驗證.py`
- `validation.py`
- `validate.py`
- `verify.py`
- `check.py`

This step must fail if no validation script exists.
This step must fail if the validation script exits with a non-zero status.
When this step fails, the workflow retries from Build with the full validation output as feedback.
