# Testing and Real-Agent Certification

## Named test profiles

```powershell
python scripts/run_tests.py --profile developer
python scripts/run_tests.py --profile commit
python scripts/run_tests.py --profile release --file-timeout 240
python scripts/run_tests.py --profile e2e
```

- `developer`: fast unit groups.
- `commit`: unit plus deterministic contract groups.
- `release`: every non-manual file in a fresh interpreter with JUnit aggregation.
- `e2e`: workflow end-to-end groups.

Every collected file receives a stable marker from `app/testing/test_catalog.py`. Release evidence includes `summary.json`, `slowest-tests.json`, `release-test-manifest.json`, and per-file JUnit XML.

## Deterministic checks

```powershell
python -m compileall -q app tests
python scripts/validate_workflow_assets.py
python -m pytest -q tests/test_stability_completion_v15.py
python -m pytest -q tests/test_unattended_stability_v16.py
python scripts/run_tests.py --profile release --file-timeout 240
```

The isolated matrix is preferred because some legacy FastAPI/TestClient tests intentionally exercise process/thread lifecycles that should not share one long-lived pytest interpreter.

## V16 unattended stability contracts

The V16 suite covers:

- connection-refused classification and model reconnect waiting;
- progress-aware retry behavior;
- profile-driven environment preflight;
- Validation Profile descriptor staleness;
- atomic delivery and post-apply validation;
- automatic restart recovery for unattended runs only;
- one Stop/cancel result;
- Simple Mode and full-height UI workspace contracts.

## UI geometry and smoke

```powershell
python scripts/run_browser_ui_smoke.py
```

Browser checks should verify at 1920×1080 and responsive widths:

- fixed Overview/Validation Run Center tabs;
- Validation below tabs;
- maximizable Technical Diagnostics;
- usable Agent/full-log height;
- visible Patch Review header;
- independently scrollable Patch file/Diff panes and Execution Artifact list/preview panes;
- one Stop dialog/state;
- model offline → online transition;
- large event streams do not freeze interaction.

## Fault-injection scenarios

Certification should include Agent no-file-change, partial write then process kill, endpoint outage and recovery, controller restart, lost session, context overflow, pre-existing baseline failures, flaky tests, protected-path edits, external project modification, stale profile, concurrent sessions, same-project writer contention, disk/resource errors, repeated no-progress failures, improving failures beyond normal retry count, and failure during final apply.

## Real-Agent Matrix

```powershell
python scripts/run_real_agent_matrix.py --mode plan
python scripts/run_real_agent_matrix.py --mode self-prompt-test --execute
python scripts/run_real_agent_matrix.py --mode real --execute --agent qwen --parallel 1
```

Track:

- user-one-request completion rate;
- first-attempt success;
- success after autonomous repair;
- retries and session rotations;
- Validation Profile reuse;
- restart recovery;
- manual intervention;
- false success;
- scope violations;
- original-project corruption.

A real release target is success after repair ≥ 90%, external validation ≥ 95%, restart resume ≥ 95%, manual intervention ≤ 10%, false success = 0, delivered scope violations = 0, and failed runs damaging the original project = 0.

Mock, dry-run, plan, and self-prompt results never count as real model certification.

### V19 local Qwen acceptance results

- Prompt acceptance: 10/10 passed.
- Real-Agent matrix: 10/10 passed.
- Success after repair: 100%.
- External-validation pass rate: 100%.
- Manual intervention: 0%.
- Scope violations: 0.
- General seven-sort one-line request: workflow completed; Agent-generated tests passed 7/7.
- Adaptive seven-sort one-line request: completed after two automatic test-layout repairs; Agent-generated tests passed 71/71.

Evidence is stored in `reports/qwen-prompt-acceptance-v19.json`, `reports/qwen-real-acceptance-v19.json`, and `reports/qwen-seven-sort-v19/`. The seven-sort runs sent only the original user requirement to the Agent; the controller did not generate product source or test files.

## Windows local-Agent cases

```powershell
.\scripts\run_local_qwen_cases.ps1 -Case all -Agent qwen -Workflow general-auto-development -Repeat 5
```

Each case uses its own Project Path and may include deterministic `validation.py`. `-DryRun` creates a plan without invoking Qwen/OpenCode.

## Optional manual environment checks

```powershell
$env:RUN_REAL_QWEN="1"
$env:RUN_REAL_QWEN_FULL="1"
$env:RUN_REAL_QWEN_STABILITY="1"
$env:RUN_CLEAN_REPO_SMOKE="1"
$env:RUN_PLAYWRIGHT_UI="1"
```

## Deterministic UI/recovery fault injection

These mock scenarios are for repeatable UI and recovery tests only. They are not real-agent evidence.

```powershell
# Scenario IDs: QWEN_MOCK_SCENARIO=fail_final_review_once, QWEN_MOCK_SCENARIO=generate_tests_no_files
$env:QWEN_MOCK="1"
$env:QWEN_MOCK_SCENARIO="fail_final_review_once"
python scripts/run_general_auto_development_e2e.py --scenario fail_final_review_once

$env:QWEN_MOCK_SCENARIO="generate_tests_no_files"
python -m pytest -q tests/test_release_and_ui_manual.py
```

Clear `QWEN_MOCK_SCENARIO` before using a real Qwen/OpenCode endpoint.

## V18 reliability and fault-injection tests

```bash
python -m pytest -q tests/test_reliability_v18.py
python scripts/run_chaos_matrix.py
python scripts/run_reliability_soak.py --iterations 200
python scripts/run_browser_ui_smoke.py --browser
```

The matrix covers blank failure normalization, quantitative repair progress, stale leases, duplicate attempts, model circuit transitions, flaky tests, process-registry cleanup, monotonically versioned UI snapshots, and single-scroll browser geometry.

## V20 unattended delivery and real-Qwen cases

```powershell
python -m pytest -q tests/test_unattended_v20.py
python scripts/run_tests.py --isolate-all --file-timeout 240
python scripts/run_real_qwen_unattended_e2e.py
python scripts/run_real_qwen_unattended_e2e.py --parallel
```

V20 contracts inject controller interruption at delivery persistence boundaries, validate full rollback, stale fencing rejection, old-SQLite migration, endpoint/model circuit isolation, project-local Agent configuration, explicit workflow phase metadata, the collapsed Run Center rail, and the large Diff dialog.

Actual Qwen execution is deliberately opt-in. The normal matrix checks the E2E runner/case contract and skips `tests/test_real_qwen_unattended_manual.py` unless `RUN_REAL_QWEN_UNATTENDED=1` or `RUN_REAL_QWEN_UNATTENDED_PARALLEL=1` is set on the target machine.

Free-form requirement text must not be parsed by controller keyword tables to decide intent, risk, complexity, scope, phase, or expected files/symbols. Validation Script generation therefore requires explicit `expectedFiles` and optional `expectedSymbols`.

## V21 Patch Review and Artifact contracts

```bash
python -m pytest -q tests/test_v21_patch_review_artifacts.py
python scripts/run_browser_ui_smoke.py --browser
```

V21 verifies removal of the Changes tab and duplicate diagnostics Patch UI, evidence-bound approval invalidation, isolated Partial Patch revalidation, explicit reject targets, explicit Artifact metadata with Unclassified legacy fallback, bounded large-Diff/Artifact preview rendering, remembered sidebar preferences, storage summaries, and real 1920×1080 geometry for the near-fullscreen workbench, independent scrolling, and focus mode.

## V22 Artifact Preview, Split Diff, and Step dialog contracts

```bash
python -m pytest -q tests/test_v22_artifact_diff_step_preview.py
python scripts/run_browser_ui_smoke.py --browser
```

V22 verifies SQLite projection hydration, legacy one-time Artifact metadata repair, real storage-path preview IDs, text/media preview coverage, binary-safe download, tool-directory exclusion from Diff and Atomic Delivery, preservation of project-local `.qwen`/`.opencode` in Agent cwd, exact equal Split Diff columns, and a dedicated Step-scoped related-file dialog.

## V23 clean release, startup, and failure contract

```powershell
python scripts/run_startup_smoke.py
python -m pytest -q tests/test_v23_release_failure_runtime.py
python scripts/build_release.py --check-only
python scripts/build_release.py
```

V23 verifies split runtime/dev/browser dependencies, the required PyYAML runtime package, an isolated FastAPI startup against temporary SQLite state, code-first Failure Contract V3, RuntimeContext compatibility, clean allowlisted release contents, per-file SHA-256 manifest data, and the extracted Executor recovery boundary.

A release ZIP must not contain controller SQLite/settings, project indexes, pytest state, reports, test results, workspaces, Python caches, or user Project Validation Profiles. Real-Agent certification remains a separate target-machine gate.

## V24 stability-convergence contracts

```powershell
python -m pytest -q tests/test_v24_stability_convergence.py
python scripts/run_tests.py --profile commit
python scripts/run_tests.py --profile release --file-timeout 240
```

V24 verifies fresh and legacy SQLite upgrades, automatic backup, migration audit metadata, future-database rejection, transactional rollback, scoped RuntimeContext overrides, legacy facade compatibility, command cwd/shell policies, timeout process-tree termination, output bounding/redaction, deterministic test markers/profiles, and a guard that prevents Runtime Facade imports from growing again.

## V24.1 Security Scan startup regression

```powershell
python -m pytest -q tests/test_v24_security_scan_hotfix.py
```

This suite verifies the report-only baseline policy, cross-platform validator CommandRunner, timeout mapping, Python validation execution, fast-terminal Run reconciliation, and the absence of direct asyncio subprocess calls in validator modules.
