# Operations

## Concurrency and resource use

Provider slots are per Agent/provider, not per Session. Different projects and sessions may run concurrently; each original project retains one writer lock. Set local model concurrency to 1 when one memory-constrained endpoint cannot serve parallel requests. Validation uses separate slots.

The platform avoids default multi-Agent review, reuses incremental indexes/profiles, sends task-scoped context, and runs focused checks before full validation.

## Model connectivity and recovery

The UI continuously probes discoverable model endpoints:

- online: slower background checks;
- offline: checks about every 2.5 seconds while visible;
- unknown/CLI-only: conservative checks;
- tab hidden: reduced polling.

Click the model indicator for an immediate check. Browser online/visibility changes also trigger re-evaluation. Workflow EventSource remains open for automatic reconnect and synchronizes the run after recovery.

For unattended runs, classified transport/connection-refused failures call a low-frequency connectivity wait before another Agent attempt. Waiting for the model does not count as repeated implementation failure.

## Watchdog

The supervisor tracks stdout/stderr activity and emits heartbeat evidence. A long model computation is not killed merely for being slow; only the configured no-output stall or total timeout ends the process. Shutdown first attempts a graceful stop, then terminates the process tree.

## Recovery budgets

Large workflow `maxRetries` values remain available for small models, but actual execution is controlled by configurable cumulative budgets:

| Scope | Default |
|---|---:|
| whole Run failures | 40 |
| one Step failures | 24 |
| one Task failures | 12 |
| same failure class | 12 |
| same fingerprint | 9 |
| wall-clock | 60 minutes |
| fresh-session rotation | every 3 same-class failures |

Progress-aware recovery does not treat a decreasing test/error set as a useless loop. Identical failure plus identical progress rotates strategy/session earlier.

## Project Validation Profile operations

Profiles are stored under the controller AI workflow data directory and do not change Git status. Verify a Draft/Stale profile before unattended work. A profile automatically becomes Stale when supported build/test/validation descriptor fingerprints change.

Environment requirements in the profile may declare commands, environment variables, and service health checks. Missing required items block unattended execution before the Agent modifies anything.

## Baseline and legacy projects

Baseline validation runs before implementation for engineering Workflows. Report-only Security Vulnerability Scan skips this phase and starts at manifest collection. Pre-existing failures are recorded as evidence when a baseline is required. Final validation blocks new/worsened failures and unmet acceptance criteria; unchanged unrelated legacy failures are not automatically assigned to the Agent.

## Isolated workspace and atomic delivery

Unattended runs default to atomic apply. Agent work occurs in an isolated effective Project Path. Delivery checks original-source fingerprints, copies only verified Agent changes, runs post-apply fast validation, and rolls back if validation regresses. Runtime artifacts and profiles remain controller-owned.

## Durable restart recovery

At startup the controller marks abandoned running work interrupted, then automatically resumes only unattended runs that explicitly carry safe restart metadata. Manual/advanced runs remain under user control. Project locks and persisted state prevent duplicate writers.

## UI operations

- Run Center and Technical Diagnostics can be collapsed/reopened.
- Technical Diagnostics can be maximized to the full viewport.
- Agent output, complete logs, Repair Strategy, Validation, Patch file/Diff panes, and Execution Artifact list/preview panes have independent scroll containers.
- Large logs/events are batched and browser-visible history is capped; complete persisted evidence remains available through artifacts/events.
- Stop is idempotent in the browser and produces one cancellation result.

## Backup and diagnostics

Back up `data/store.sqlite3`, `data/settings.json`, global workflow assets, controller project profiles, and required project `.ai-workflow/runs` evidence. For investigation use Overview first, then Technical Diagnostics, Debug Bundle, consistency checks, artifact repair, Run comparison, and benchmark reports.

## Safe release procedure

```powershell
python -m compileall -q app tests scripts
python scripts/run_startup_smoke.py
python scripts/validate_workflow_assets.py
python scripts/run_tests.py --profile release --file-timeout 240
python scripts/run_production_acceptance.py
python scripts/build_release.py --check-only
python scripts/build_release.py
```

Run the real-Agent matrix on the target Windows/Qwen/OpenCode environment before claiming real-model certification.

## Known limitations and review mode

- Small/local models may plan correctly but fail to create or modify files. This becomes `NO_FILE_CHANGE`; the controller rotates recovery strategy/session and never materializes text blocks as code.
- Use `patchMode=review` for unfamiliar, high-risk, or policy-sensitive projects when explicit human approval is preferred over unattended atomic delivery.
- SQLite/provider slots target one local machine, not a distributed multi-node control plane.
- Before promotion, run `scripts/run_production_acceptance.py` and the real-Agent matrix on the actual model/CLI environment.

## V18 unattended reliability controls

V18 adds four controller-owned protections that do not modify project source files:

- **Run lease:** one live Controller owns a Run at a time. Expired leases can be recovered after restart.
- **Idempotent attempts:** a completed Step attempt is not executed again after reconnect or restart.
- **Model circuit breaker:** repeated endpoint failures pause new Agent calls; one half-open probe resumes the queue after recovery.
- **Process registry:** managed Agent and validation processes are recorded and orphaned children are reaped when the Controller starts.

Recommended pre-pilot checks:

```bash
python scripts/run_chaos_matrix.py
python scripts/run_reliability_soak.py --iterations 200
python scripts/run_browser_ui_smoke.py --browser
```

Increase soak iterations for overnight testing. Real Qwen/OpenCode certification remains separate and opt-in.

## Release artifact policy

Do not zip the working directory directly. `scripts/build_release.py` uses an allowlist and writes `RELEASE_MANIFEST.json` plus a sidecar manifest. Keep the sidecar with release evidence so support can verify exactly which files and hashes were delivered.

Runtime state is intentionally excluded. Backups and release packages are different artifacts: back up SQLite/settings/profiles for recovery, but never distribute them in the product ZIP.

## Database migration operations

Startup applies only missing SQLite migrations. Before changing an existing schema, the controller creates one `pre-migration` backup unless `AIWF_SQLITE_AUTO_BACKUP=0`. Keep automatic backup enabled for normal local operation. Migration failure blocks startup and leaves the failed version unapplied. `DATABASE_SCHEMA_TOO_NEW` means the database belongs to a newer controller and must not be downgraded in place.

After an upgrade, verify `/ready`, `/api/health/deep`, and `/api/maintenance/store/status`. For rollback, restore the pre-migration backup before starting the older program version.

## CommandRunner operations

Project commands are executed only from a cwd inside the declared Project Path. Agent-generated commands must be argv-only and cannot enable shell mode. Command output is UTF-8 normalized, redacted, and bounded; timeout terminates the full process tree. Investigate `TIMEOUT` and `COMMAND_FAILED` through validation artifacts rather than rerunning commands outside the controller with different cwd/environment.
