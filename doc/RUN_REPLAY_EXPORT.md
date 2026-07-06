# Run Replay and Export

## Export

```text
GET /api/workflow-runs/{run_id}/export
```

Exports a zip bundle containing:

- bundle-manifest.json
- run.json
- run workspace prompts, outputs, trace, and gate report

## Replay

```text
POST /api/workflow-runs/{run_id}/replay
```

Creates a fresh run with the same workflow, requirement, project, validation script, test command, model profile, and thinking level by default.

Use replay to compare agents or reproduce failures.
