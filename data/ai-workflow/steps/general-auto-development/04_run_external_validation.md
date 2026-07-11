This is a Python function step.

It runs the immutable user validation contract for this run when one is configured.

Run-specific validation script:
{{validation_script}}

Fallback script names are used in this priority order only when the run allows discovery:
{{fallback_validation_scripts}}

Behavior:
- If a required validation contract is configured, its original file must exist, its SHA-256 must match, and it must execute with exit code 0.
- If optional validation is not configured, write `Status: NOT_CONFIGURED`; never report a fake PASS.
- If a required validation file is missing, changed, blocked, or times out, stop with structured validation evidence.
- If validation exits non-zero, fail this step and pass the concrete command, exit code, stdout, and stderr back to the related task as repair feedback.
- After repair, execute the same immutable validation contract again. Agent text cannot substitute for execution evidence.
- Do not ask Qwen/OpenCode to perform validation here; this is a controller gate.
