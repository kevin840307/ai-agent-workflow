# V12 UI Review and Local Qwen Cases Test Report

## Scope

V12 focuses on the user review flow instead of adding another main panel:

- Replace the lower/right result dock with one center result dialog.
- Make Changes usable inside a narrow Run Center.
- Give unified and split Patch views independent scrollbars.
- Add repeatable real Qwen/OpenCode cases with one-line prompts and required validation evidence.

## UI changes

### Workflow result

- One centered modal only.
- Close with the explicit close button, backdrop click, or Escape.
- Reopen from the Run Center `結果` button.
- No fixed result summary near the composer or bottom edge.

### Changes

- Compact summary metrics.
- File navigator and preview are stacked vertically.
- Only one selected-file preview is authoritative.
- Diff preview has its own vertical and horizontal scroll area.
- The Run Center itself is not forced into two narrow columns.

### Advanced Patch Review

- The diagnostics drawer expands only for Patch Review.
- File selection and Diff preview own separate scroll areas.
- Unified view uses a wide preformatted surface with horizontal scrolling.
- Split view preserves independent Before/After content without stretching the page.
- Narrow screens fall back to one vertical review flow.

## Local real-agent cases

Six cases are included under `examples/real_qwen_cases/`:

1. `bubble_sort_new`
2. `fix_existing_sort_bug`
3. `root_pytest_update`
4. `json_config_loader`
5. `csv_summary`
6. `repair_validation_failure`

Each case contains:

- One-line `prompt.txt`
- `project_seed/`
- Required, read-only `validation.py`
- `case.json` expected-file metadata

Runner:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_local_qwen_cases.ps1 -Case all -Agent qwen
```

A case passes only when the Controller reports `done`, the required files exist, and `validation.py` independently exits with code 0 after the Workflow.

## Verification

### UI and compatibility contracts

```text
79 passed
63 subtests passed
```

Covered V8, V9, V10, V11 and V12 UI/runtime contracts.

### CLI and agent runtime contracts

```text
60 passed
```

Covered Qwen/OpenCode provider behavior, `/wf`, `/wstep`, session handling, and stable launcher routing.

### V12-specific tests

```text
6 passed
```

Covered stacked Changes layout, Patch scroll ownership, center result modal, case manifests, dry-run reports and Windows wrapper packaging.

### Static browser smoke

```text
PASS
```

Validated dismissible modal, stacked Diff, selective Patch Review, diagnostics close behavior and layout overflow rules.

### Production Acceptance (quick)

```text
compileall                     PASS
JavaScript node --check        44 / 44 PASS
Workflow asset validation     PASS
Static browser UI smoke       PASS
Crash recovery simulation     PASS
/wf and /wstep route smoke    PASS
```

### Test matrix coverage

```text
50 / 50 test files assigned
missing: 0
extra: 0
duplicates: 0
```

The complete isolated matrix was started, but the long runner was stopped by the execution environment after completed test modules had passed; this report does not claim a new complete 50-file run. The changed UI/CLI/runtime surfaces and Production Acceptance gates were run separately and passed.

## Real Qwen note

This environment does not provide the user's actual Windows Qwen model endpoint. The package therefore includes deterministic dry-run tests and the local real-agent runner, but does not claim that all six cases were executed here with the user's real Qwen model.
