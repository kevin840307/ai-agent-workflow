# Workflow Stability Plan

This project uses three verification layers:

1. **Unit / contract tests**: parser, retry, guard, API, and workflow asset behavior.
2. **Self-prompt E2E**: deterministic mock agent acts like Qwen/OpenCode and runs the real FastAPI workflow APIs.
3. **Real-agent smoke**: optional Qwen/OpenCode run for a small prompt, with replay bundle and logs.

## General Auto Development canonical flow

```text
plan_tasks
-> build
-> generate_tests
-> run_test
-> implementation_review
-> run_external_validation
-> final_review
-> final_gate
```

`final_review` is deterministic Python verification. AI review may report risks, but Python tests and validation decide PASS/FAIL.

## Stability score

Self-prompt and smoke scripts write `stability-report.md` using:

- terminal run status
- retry count
- failed steps
- expected source/test files
- manual validation result
- workflow validation result

Scores are comparable across workflow changes. A lower score does not replace failure; it explains risk.

## Failure-injection matrix

Recommended required E2E cases:

| Case | Expected controller behavior |
|---|---|
| no file changes | retry owning edit step |
| validation fails once | retry build/auto_generation, then pass |
| AI review fails once | retry owning edit step, then pass |
| tool-call JSON / prose only | fail or reprompt; no platform FILE materialization in real mode |
| project-outside write | hard fail by path guard |
| repeated same failure | escalate from edit step back to planning step |

## Project isolation option

For stricter deployments, run the agent against a copied workspace:

```text
copy project -> run agent in workspace/agent-project -> diff -> validate -> apply reviewed patch
```

The helper module `app.security.isolated_workspace` implements this opt-in pattern.
