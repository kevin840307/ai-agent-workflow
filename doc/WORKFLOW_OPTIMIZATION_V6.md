# Workflow Optimization V6

This release hardens both **General Auto Development** and **Adaptive Auto Workflow** using the same execution, retry, validation, and project-safety rules.

## 1. Project Path is the real agent working directory

For the normal `auto_apply` mode, the selected project is always the actual CLI working directory and write root.

Example:

```text
Selected Project Path: C:\Projects\sort2
Qwen/OpenCode cwd:     C:\Projects\sort2
Generated source:      C:\Projects\sort2\...
Workflow metadata:     C:\Projects\sort2\.ai-workflow\runs\...
```

`.ai-workflow` stores prompts, logs, state, evidence, and reports only. Product/source/test files must not be generated in the run workspace.

Isolation is used only when `patchMode` is explicitly `review` or `dry_run`.

## 2. Filesystem-first build decisions

A malformed or incomplete agent summary no longer discards valid edits. After every build task, the controller compares the project filesystem before and after the CLI call. If source/test files were created, those files are validated and treated as the candidate result even when the provider output parser reports an error or timeout after the write completed.

Tool transcripts such as `Successfully overwrote file...` are live status events, not build artifacts or errors.

## 3. Safe rollback and session reconciliation

Rollback is limited to deterministic failures such as failed tests, failed validation, protected-path writes, or missing required files. Parser, summary, session, and context failures preserve candidate files for deterministic verification.

When a deterministic failure causes rollback, the next build call uses a fresh agent session so model memory cannot disagree with the restored filesystem.

## 4. Retry behavior

Retry history is keyed by the real failing step, task ID, failure class, and fingerprint. The retry target is recorded separately. A Build failure is no longer counted as a Planner failure.

- Review JSON/readonly violations retry Review.
- Build/test failures repair the current task.
- Replanning occurs only for explicit plan/spec conflicts.
- Repeated identical failures stop early.
- Normal retry limits are 6 instead of 99.
- Each generated task receives its own timeout budget.

## 5. Read-only planning and review

Planning and review steps use fresh sessions and are protected by a read-only filesystem snapshot. Any project mutation made by a Planner or Reviewer is reverted and classified as a review/planning violation.

## 6. Complexity-aware planning

The controller classifies requests as `tiny`, `standard`, or `complex` from requirement and project evidence.

| Profile | Maximum planned tasks | Intended use |
|---|---:|---|
| tiny | 2 | One function, small fix, small file change |
| standard | 5 | Feature spanning several files or tests |
| complex | 10 | Cross-module/service, migration, architecture work |

Prompts require minimum sufficient scope and reject unnecessary duplicate modules, examples, documentation, or speculative features.

## 7. Deterministic validation and hygiene

Python validation order:

1. Configured validation script
2. Pytest suite
3. `run_tests.py`
4. Python source without executable validation: `FAIL / VALIDATION_NOT_EXECUTED`
5. Non-Python project: explicit `SKIPPED`

The final hygiene gate detects:

- duplicate public implementations;
- root-level tests duplicated beside `tests/`;
- tests that redefine production functions instead of importing them;
- redundant test entry points.

Validation status in the final gate is derived from the actual validation artifact, preventing `pytest PASS` from being reported as `SKIPPED`.

## 8. Review evidence

Structured review output includes acceptance criteria and concrete evidence. Reviewer confidence is capped when evidence is missing; a plain self-declared `confidence: 1.0` is not sufficient for a fully trusted pass.

## 9. Failure feedback size

Retry feedback keeps only the latest three compact entries and truncates raw error content. Full transcripts remain available in the run log, but source files and repeated tool output are not re-injected into Planner prompts.
