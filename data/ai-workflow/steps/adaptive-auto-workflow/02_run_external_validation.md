# Adaptive Auto Workflow - Run External Validation

This Python step uses the shared `run_external_validation` function.

Behavior:

- If the run has no `validation_script`, write `Status: PASS` and skip validation.
- If `validation_script` is provided, execute that Python file in the selected project path.
- If the script exits with non-zero status, write stdout/stderr to `external-validation-result.md` and retry from `auto_generation` with the error message as repair feedback.

The validation script may accept these optional arguments:

```text
--project <project_path> --workspace <run_workspace> --output <output_dir>
```

If the script does not accept those arguments, the runner retries it as plain `python <script>`.
