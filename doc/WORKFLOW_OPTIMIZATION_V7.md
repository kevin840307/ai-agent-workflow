# Workflow Optimization V7

V7 completes the deterministic repair layer discovered by real General Auto Development and Adaptive Auto Workflow runs. It keeps product files in the selected Project Path and uses AI only when the controller cannot safely repair the failure itself.

## 1. Project Path remains the source of truth

In normal `auto_apply` mode, Qwen/OpenCode runs directly in the selected project directory.

```text
Selected Project Path: C:\Projects\sort2
Agent cwd/write root:  C:\Projects\sort2
Controller metadata:   C:\Projects\sort2\.ai-workflow\runs\...
```

Source and test files are created under the selected project. `.ai-workflow` stores only prompts, state, logs, evidence, reports, and run metadata.

## 2. Phase file ownership is enforced

Prompt instructions are no longer the only protection. After each agent call, the controller classifies the actual filesystem diff and restores only files that the current phase does not own.

- Build owns production files and must not keep `test_*.py`, `*_test.py`, or `tests/**` changes.
- Generate Tests owns canonical test files under `tests/**` and must not keep production-source changes.
- Mixed agent output is salvaged: valid production files are preserved while only wrong-phase test files are restored, and vice versa.
- User files that existed before the step are restored from the pre-step snapshot rather than deleted.

## 3. Deterministic test-layout repair

Before pytest or the adaptive Python gate runs, the controller performs a safe layout preflight.

It may remove a root-level `test_*.py` only when all of the following are true:

1. the file did not exist in the run baseline;
2. it was created by the current run;
3. a canonical counterpart exists under `tests/`, or the root file is empty while canonical tests exist.

Pre-existing user tests are never removed automatically. The repair also clears run-created pytest/Python caches and writes `output/test-layout-repair.json` as evidence.

## 4. Pytest import mismatch recovery

Errors such as:

```text
import file mismatch
```

are classified as `TEST_LAYOUT_CONFLICT`, not as an unknown implementation failure. The controller performs deterministic cleanup and retries pytest once without consuming an AI retry. Production code is not modified for this failure class.

## 5. Timeout recovery uses a fresh session

After an agent timeout, the next retry uses a fresh Qwen/OpenCode session. The controller first preserves and validates any filesystem changes already produced. It does not resume the same timed-out session repeatedly while model memory and project state diverge.

## 6. Retry accounting belongs to the failing step

The controller now separates:

- source step that failed;
- recovery target;
- cumulative attempt count;
- consecutive failure streak.

A Review failure that returns to Build consumes Review's retry budget, not Build's budget. A successful step resets its consecutive-failure streak while retaining cumulative attempts for reporting.

## 7. Compact repair feedback includes a stop condition

Failure feedback records the failure class, repair strategy, concrete error, and deterministic stop condition. Examples:

- tests: configured test command exits 0;
- validation: validation script exits 0;
- path guard: all writes are inside Project Path;
- no file change: required project diff exists and passes acceptance checks.

Only the latest three compact feedback entries are injected into retries.

## 8. Reduced default retry budgets

Normal workflows no longer rely on a 99-attempt loop.

- Planning/review formatting: up to 2 retries.
- Build/auto generation: up to 3 retries.
- Test execution: up to 3 retries.
- Deterministic layout cleanup does not consume AI retry budget.

Repeated identical failures still stop early.

## 9. Scope control for small tasks

Tiny-task prompts require minimum sufficient implementation:

- no unrequested public parameters;
- no duplicate implementation modules;
- no unnecessary examples or documentation;
- one canonical production layout and one canonical test layout.

## 10. Expected behavior for the observed bubble-sort failures

### General Auto Development

```text
Build creates bubble_sort.py plus an invalid root test
-> keep bubble_sort.py
-> restore/remove only the wrong-phase root test
-> Generate Tests creates tests/test_bubble_sort.py
-> layout preflight
-> pytest PASS
```

### Adaptive Auto Workflow

```text
Agent creates source, canonical tests, and an empty root test
-> remove only the run-created empty root test
-> pytest PASS
-> hygiene PASS
-> review/final gate PASS
```

Neither case requires repeated AI regeneration solely to delete a controller-owned duplicate test file.
