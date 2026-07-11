# Production Readiness V10

V10 defines a non-bypassable completion contract for local and internal single-machine deployments.

## Reliability guarantees

- Filesystem diff and deterministic evidence, not agent prose, decide success.
- Required user validation is resolved at Run creation, hashed, protected read-only, executed with a timeout, and rerun after every repair.
- Missing, changed, blocked, timed-out, or non-zero required validation cannot become PASS.
- Retries target the owning Task/Step; valid completed Tasks are preserved by checkpoints.
- Rollback, timeout, context handoff, and filesystem restore use a fresh Agent Session plus current filesystem facts.
- Final completion reloads the latest SQLite state and requires tests, required validation, accepted Tasks, resolved Step state, and no unresolved policy violation.
- Test modules run in isolated pytest interpreters during Production Acceptance to prevent background-task teardown from contaminating the matrix.

## Supported product workflows

1. Adaptive Auto Workflow
2. General Auto Development
3. Security Vulnerability Scan

Internal workflow parsers and plugin APIs remain extensible, but unsupported custom workflows are not exposed in the product catalog.

## User validation contract

A configured required validation file records its absolute path, SHA-256, working directory, timeout, requirement flag, and read-only policy. Repairs must rerun the same original contract and produce exit-code-zero evidence. Optional missing validation is `NOT_CONFIGURED`, never a fabricated PASS.

## UI review flow

- Environment reminders are compact, non-blocking, dismissible, and remember dismissal.
- Changes use one file-first surface with exact line counts and readable line-numbered diffs.
- Advanced Patch Review uses a compact file rail, search, selection, unified/split preview, approval, and selective apply.
- Console, raw prompts, artifact index, repair policy, and debug data remain in the dismissible Technical Diagnostics drawer.

## Deployment scope

V10 is production-ready for controlled local/internal single-machine deployment with one FastAPI worker and SQLite WAL. Public multi-tenant or internet-facing deployment still requires organization-specific authentication, authorization, secret management, network hardening, and centralized audit retention.
