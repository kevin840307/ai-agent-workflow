# V21 Verification Report

## Result

**PASS**

## Full isolated matrix

- Test files: **59/59**
- Coverage assignment: **59/59**
- Tests: **728**
- Passed: **718**
- Skipped: **10**
- Failures: **0**
- Errors: **0**
- Elapsed: **380.13s**

The 10 skipped tests are explicit environment/manual gates: real Qwen runs, clean-repository smoke, and optional Playwright manual wrappers. The dedicated Chromium smoke was executed separately and passed.

## Browser UI

Real Chromium, viewport 1920×1080:

- Status: **PASS**
- Run Center tabs: **2**; Changes tab count: **0**
- Patch workbench: **1904×1064**
- Patch content width: **1622px**
- File sidebar width: **280px**
- Independent file/Diff scrolling: **PASS**
- Focus mode expansion: **PASS**
- Artifact master-detail and independent scrolling: **PASS**
- Artifact storage/load-more controls: **PASS**
- Duplicate diagnostics Patch UI: **absent**

## Workflow and production gates

- Workflow Asset validation: **PASS**, 3 workflows, 0 errors, 0 warnings.
- Quick Production Acceptance: **PASS**, 50/50 checks.
- Python compilation: **PASS**.
- Front-end JavaScript syntax: **PASS**.
- CSS parsing: **PASS**.

## Reliability evidence

- Chaos Matrix: **5/5 PASS**.
- Reliability Soak: **200/200 PASS**.
- Remaining managed processes: **0**.
- Active leases after soak: **0**.
- Process registry after final acceptance: empty.

## Evidence files

- `reports/full-test-matrix-v21.json`
- `reports/browser-ui-v21.json`
- `reports/workflow-assets-v21.txt`
- `reports/chaos-matrix-v21.json`
- `reports/reliability-soak-v21.json`
- `reports/production-acceptance-v21-quick/production-acceptance-report.json`

## Real model note

Real Qwen/OpenCode execution remains opt-in because this environment does not represent the user’s installed CLI, endpoint, model, and project configuration. Contract tests verify the real-runner behavior, distinct sessions, effective cwd, project-local config preservation, and refusal to claim a Mock run as real.
