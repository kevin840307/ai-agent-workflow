# AI Workflow V18 Production Acceptance

Generated: 2026-07-11T13:51:52.470174+00:00

## Result

**PASS** for deterministic platform, UI, recovery, concurrency and mock/self-prompt acceptance.
Real Qwen/OpenCode certification still requires the user's Windows environment and is not represented by mock results.

## Evidence

| Gate | Result |
|---|---:|
| Full isolated matrix | PASS — 683 tests, 675 passed, 8 skipped, 0 failures/errors |
| Test file coverage | 55/55 files |
| Quick production gate | PASS — 49 checks |
| Workflow assets | PASS — 3 workflows, 0 warnings |
| Real Chromium geometry | PASS |
| Reliability soak | PASS — 1000/1000 iterations, 0 open processes, 0 active leases |
| Fault-injection matrix | PASS — 5/5 cases |
| Self-prompt General + Adaptive | PASS |
| Regression template E2E | PASS |
| Workflow soak | PASS — 2 runs |
| Crash recovery | PASS |

## V18 acceptance scope

- persisted Run lease and idempotent Step attempt protection;
- model circuit breaker and offline recovery;
- non-empty normalized failure evidence;
- progress-aware high-retry recovery;
- suspected flaky-test detection without hiding stable failures;
- managed-process registry and orphan cleanup;
- restart-idempotent atomic delivery and rollback;
- monotonic UI Run state versions;
- large Step dialog and one vertical scrollbar per primary work surface;
- Apply to Project beside Split/Unified Patch controls;
- large technical artifact viewing without nested vertical scroll traps;
- bounded Agent/Log DOM rendering.

## Constraints

- The controller does not generate requested project source files. Qwen/OpenCode must edit from the effective Project Path cwd.
- Eight skipped tests require real Qwen, a clean repository, or explicitly enabled browser/manual environments.
- Real-agent certification plan contains 20 Qwen/OpenCode × Workflow × Case cells and must be executed locally before claiming model-level unattended success.
