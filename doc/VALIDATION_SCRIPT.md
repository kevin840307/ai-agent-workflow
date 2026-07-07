# Validation Script

A validation script is an optional Python acceptance gate.

The controller checks, in order:

1. Run request `validation_script`
2. `validation.py`
3. `validate.py`
4. `verify.py`
5. `check.py`
6. pytest tests if present
7. skipped PASS

The script is executed from Project Path. The controller first tries:

```bash
python validation.py --project <project> --workspace <run-workspace> --output <output-dir>
```

If the script rejects those arguments, it falls back to:

```bash
python validation.py
```

## First-class validation behavior

Validation scripts are treated as deterministic gates, not as optional prose review.

The runner attempts this command first:

```text
python validation.py --project <project_path> --workspace <run_workspace> --output <output_dir>
```

If the script rejects these arguments with an argument-error message, the runner falls back to:

```text
python validation.py
```

A workflow may provide `validation_script` explicitly, or a step may define fallback candidates such as:

```yaml
fallbackValidationScripts:
  - validation.py
  - validate.py
  - verify.py
  - check.py
```

A missing script is PASS only when `requiresValidationScript: false`; otherwise the step writes `external-validation-result.md` with `Status: FAIL`.

The deterministic precedence is:

```text
pytest / validation.py / Python gate > AI review text
```
