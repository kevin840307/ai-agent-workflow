# Local-First Agent Workflow System Architecture

This project is designed for local single-user execution while keeping the core architecture platform-grade.

## Local-first means

- File or SQLite backend, no mandatory server database.
- Single-project single-writer lock instead of distributed locking.
- Patch Review is preferred for real agents before applying changes to the original project.
- All Qwen/OpenCode/generic CLI calls run through the shared process supervisor.
- Every workflow run writes a complete artifact bundle that can be exported locally.
- Cleanup/retention is local and conservative: active runs are never deleted.

## Local-first does not mean

- Skipping state consistency.
- Letting agent subprocesses bypass cwd / timeout / cancel supervision.
- Allowing workflow assets to be unvalidated.
- Treating artifacts/logs as best-effort only.

## Core architecture

```text
UI Workflow Console
→ API Routes
→ Workflow Engine Kernel
→ Step Executor / Action Registry
→ Agent Supervisor / Python Functions
→ RunStore / StepStore / ArtifactStore / EventStore / LockStore
→ Standard Artifacts / Events / Reports
```

## Safety defaults

- Real agents default to `patchMode=review`.
- Same project allows one active writer.
- Restart recovery clears stale locks.
- `events.jsonl`, `state.json`, `final-report.md`, and `debug-bundle.json` are standard output artifacts.
