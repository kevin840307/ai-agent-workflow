# Known Limitations

This project is suitable for controlled internal pilot usage, but the following limits must remain visible to operators and users.

## Agent/model behavior

- Small/local models may plan correctly but fail to create or modify files.
- Real Qwen/OpenCode behavior depends on the installed CLI, model, tool permissions, and prompt mode.
- Repeated `NO_FILE_CHANGE` failures should be treated as an agent/tooling issue, not only as a workflow retry issue.

## Safe execution mode

- Real agents use `patchMode=auto_apply` by default so generated files are written to the selected project. Set `AIWF_DEFAULT_PATCH_MODE=review` or pass `patchMode=review` to use an isolated approval workspace.
- For production repositories that require approval, explicitly use `patchMode=review`.
- Patch review or dry run mode uses an isolated workspace and requires user approval before applying changes.

## Storage/backend

- File backend is suitable for individual use and internal pilot.
- SQLite backend is available for transactional single-node usage.
- Large multi-user production deployments should move toward a normalized DB schema and explicit auth/audit controls.

## Concurrency

- One project should have only one active writer run at a time.
- Cross-project parallelism is supported in concept, but should be validated with soak/stress tests before broad rollout.
- Cancel/timeout/restart recovery exists, but real agent subprocess behavior can vary by OS and CLI.

## Test strategy

- Use `scripts/run_tests.py` matrix groups for CI.
- A single long `pytest -q` process can mix TestClient/background workflow state and is not the recommended production gate.
- Use `scripts/run_production_acceptance.py` to produce a promotion report.

## UI validation

- Static UI smoke checks are included.
- Full browser screenshot/visual regression requires Playwright browser installation and should be enabled in CI before wide rollout.

## Artifacts and retention

- Workflow artifacts can grow quickly under `.qwen-workflow` / `.ai-workflow`.
- Configure retention cleanup for long-running pilots.
- Always export important run bundles before cleanup.
