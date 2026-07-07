# Productization Next Improvements

This round turns the workflow runner from a runnable demo into a more product-ready agent workflow platform.

## Added MVP features

1. **Run Console / Timeline API**
   - `GET /api/workflow-runs/{run_id}/console`
   - Returns step durations, retry totals, failure classes, recent step events, and timeline items.
   - Also writes `.workflow/run-console.json` at run completion.

2. **Queue / Cancel / Timeout Control**
   - `GET /api/workflow-runs/active`
   - `GET /api/workflow-runs/queue`
   - `POST /api/workflow-runs/{run_id}/cancel`
   - Create run supports `runTimeoutSec`.

3. **Patch Approval Mode**
   - Create run supports `patchMode`: `auto_apply`, `review`, or `dry_run`.
   - `review` / `dry_run` copy the selected project into a run-local isolated workspace.
   - `GET /api/workflow-runs/{run_id}/patch` previews changed files and diff.
   - `POST /api/workflow-runs/{run_id}/patch/apply` applies reviewed isolated changes back to the original project.
   - Writes `.workflow/patch-approval.json` / `.workflow/patch-approval.md`.

4. **Prompt / Workflow Versioning**
   - Create run supports `workflowVersion`, `promptVersion`, and `contractVersion`.
   - `GET /api/workflow-runs/{run_id}/version-meta` returns version metadata.
   - Writes `.workflow/version-metadata.json`.

5. **Benchmark Dashboard API**
   - `GET /api/workflow-benchmarks`
   - Aggregates runs by workflow, pass rate, retry average, failure classes, and unstable steps.

6. **Workflow Designer Validator**
   - `GET /api/workflows/validate`
   - Runs workflow lint against system/custom workflows and reports issues before users save/run invalid flows.

7. **Real Agent Matrix Test Planner**
   - `POST /api/real-agent-matrix`
   - `scripts/run_real_agent_matrix.py`
   - Generates the matrix of agent × workflow × case commands for real Qwen/OpenCode smoke tests.

8. **Context Pack / Skill Pack**
   - `GET /api/context-packs`
   - `GET /api/context-packs/{pack_id}`
   - `PUT /api/context-packs/{pack_id}`
   - Packs reusable project knowledge such as architecture, coding rules, DB schema, SOP, and validation rules.
   - Create run supports `contextPack`, which injects pack content into the requirement context.

## UI cleanup

- Composer `Model` label was replaced with `Profile`.
- `Debug tools` was renamed back to `Advanced`.
- Advanced step actions now expose Console, Run Diff, Patch, Version, Export, and Replay tools.
