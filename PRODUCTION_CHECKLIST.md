# Production Checklist — V11

## Before deployment

- [ ] Back up `data/store.sqlite3`.
- [ ] Use one FastAPI worker.
- [ ] Confirm project directories are local/trusted and writable.
- [ ] Run Setup Smoke Test for the selected Agent/model.
- [ ] Configure the model's actual Context Window.
- [ ] Run `python scripts/validate_workflow_assets.py`.
- [ ] Run `python scripts/run_production_acceptance.py --quick --output reports/production-acceptance-v11`.
- [ ] Run the real-agent matrix on the target Windows environment.
- [ ] Reinstall Agent commands and confirm `/wf` and `/wstep` route verification passes from a non-Controller project.
- [ ] In Qwen/OpenCode TUI, type `/` and confirm both commands are visible.

## Before unattended auto-apply

- [ ] Tiny/Small benchmark pass rate meets the team threshold.
- [ ] Required validation files are stored in protected project paths.
- [ ] Medium/high-risk work uses Review/Patch approval.
- [ ] Backup and rollback procedures have been tested.
- [ ] Long-running restart recovery has been tested on the target machine.

## Production invariants

- [ ] Required validation skipped = 0.
- [ ] Run completed without test/validation evidence = 0.
- [ ] Rollback followed by stale Session resume = 0.
- [ ] Repeated no-progress retry beyond policy = 0.
- [ ] Original user file deleted outside accepted Task scope = 0.
- [ ] Project lock left behind after stop/restart = 0.
