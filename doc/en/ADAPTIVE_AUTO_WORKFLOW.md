# Adaptive Auto Workflow

Adaptive Auto Workflow is the simple auto-development loop. It is designed for the case where the user provides one requirement and expects the system to generate, review, validate, and repair automatically.

## Flow

```text
Requirement
  -> Step 1: Auto Generation
  -> Step 2: AI Review
  -> Step 3: Run External Validation optional
  -> failed review / validation returns feedback to Step 1
```

## Step 1: Auto Generation

The agent reads the requirement and the selected project, then writes the required production files, tests, or documentation directly inside the selected Project Path.

## Step 2: AI Review

A reviewer session checks the generated result. If the review fails, the feedback is returned to Step 1 for repair.

## Step 3: Run External Validation

This step uses the shared `run_external_validation` Python function.

Behavior:

- Empty validation script: skip the external validation and return `Status: PASS`.
- Python validation script provided: execute it.
- Non-zero exit code: write stdout, stderr, and exit code to `external-validation-result.md`, then return the failure message to Step 1.

## Validation script examples

Relative path:

```text
tools/validate_config.py
```

Absolute path:

```text
C:\work\validators\validate_config.py
```

The runner first tries:

```text
python <script> --project <project_path> --workspace <run_workspace> --output <output_dir>
```

If the script does not support these arguments, it falls back to:

```text
python <script>
```
