This is a Python function step.

It runs the user validation script for this run when one is configured or present.

Run-specific validation script:
{{validation_script}}

Fallback script names are used in this priority order when no run-specific script is set:
{{fallback_validation_scripts}}

Behavior:
- If a validation script exists, execute it and write `output/external-validation-result.md`.
- If no validation script exists, write a skipped PASS result and continue.
- If validation exits non-zero, fail this step and pass the concrete output back to Execute Task Loop as repair feedback.
- Do not ask Qwen/OpenCode to perform validation here; this is a controller gate.
