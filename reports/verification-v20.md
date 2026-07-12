# V20 Verification Report

## Automated test matrix

- Status: **PASS**
- Mode: isolated, one Python process per test file
- Test files: **58 / 58**
- Tests: **712**
- Passed: **702**
- Skipped: **10**
- Failures: **0**
- Errors: **0**
- Elapsed: **397.57 seconds**

The 10 skips are deliberate opt-in/environment tests, including real Qwen execution and manual environment checks. They are not converted into mock passes.

## Browser UI verification

- Status: **PASS**
- Browser: Chromium (`/usr/bin/chromium`)
- Viewport: 1920px wide
- Diff dialog: 1500 × 900
- Dedicated Diff dialog: PASS
- Changed-file list scrolling: PASS
- Diff content scrolling: PASS
- Run Center collapse/reopen: PASS
- Run Center maximize control removed: PASS through UI/static contracts
- Step detail dialog and diagnostics workspace: PASS

## Chaos matrix

- Status: **PASS**
- Cases: **5 / 5**
- Model offline recovery: PASS
- Duplicate Attempt protection: PASS
- Stale Lease takeover: PASS
- Flaky-test detection: PASS
- Repair-progress detection: PASS

## Reliability soak

- Status: **PASS**
- Iterations: **200 / 200**
- Open managed processes after completion: **0**
- Active leases after completion: **0**

## Additional verification

- Python compile: PASS
- Front-end JavaScript syntax checks: PASS
- Workflow Asset validation: PASS, 3 workflows, 0 errors, 0 warnings
- Static UI smoke: PASS
- SQLite V2-to-V3 migration test: PASS
- Delivery-journal crash-boundary rollback tests: PASS
- Same/different project concurrency contracts: PASS
- Restart recovery and Completion Gate tests: PASS

## Real Qwen E2E status

The real-Qwen runner, fixtures, contract tests, sequential mode, and parallel distinct-session mode are included. Actual Qwen model execution was **not run in this build environment**, because the target Qwen CLI, local model endpoint, and project-local configuration belong to the deployment machine.

Run locally:

```powershell
python scripts/run_real_qwen_unattended_e2e.py
python scripts/run_real_qwen_unattended_e2e.py --parallel
```

The runner rejects mock mode, validates effective Agent cwd and copied project-local configuration, checks Agent-created files and validation evidence, and confirms distinct Workflow/Qwen session IDs for parallel cases.
