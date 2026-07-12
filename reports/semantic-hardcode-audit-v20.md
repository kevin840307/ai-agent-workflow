# V20 Semantic Hardcode Audit

## Result

**PASS for production/runtime decision paths.**

The Controller no longer classifies free-form user requirement text with keyword tables, substring checks, or regular expressions to decide:

- request intent or whether work is a development task;
- new-project versus existing-project behavior;
- risk or approval mode;
- complexity;
- scope/path selection;
- optimization recommendations;
- Workflow Step phase or Agent session role;
- review/validation evidence category;
- Validation Script filenames, expected symbols, or regression CaseId.

## Replacement contracts

Runtime decisions now use explicit machine-readable fields and structural evidence:

- `phase`
- `sessionRole`
- `evidenceCategory`
- `workflowInputs.caseId`
- `expectedFiles`
- `expectedSymbols`
- Project Validation Profile state and executed-validator evidence
- filesystem/project structure metrics

Referenced Markdown is preserved structurally through headings and lists. It is not classified by natural-language keywords.

## Allowed exact parsing

Exact matching remains only for machine protocols, such as JSON/YAML keys, enum values, CLI events, error codes, test-runner output, and deterministic test-double protocols. These checks validate a defined format and do not infer the meaning of user prose.

## Test-only boundary

`app/testing/*` contains deterministic mock/test agents that return fixed test fixtures. They are activated only through mock test configuration and are not used to route or execute production Qwen/OpenCode runs. Requested project files in real runs are still created exclusively by Qwen/OpenCode in the effective Project Path.

## Verification

- `tests/test_unattended_v20.py` rejects known legacy semantic-pattern constants and requirement-lowercasing paths.
- Workflow contract tests require explicit `phase`, `sessionRole`, and validation evidence metadata.
- Regression CaseId tests require `workflowInputs.caseId` instead of extracting identifiers from requirement prose.
- The full isolated test matrix passed with zero failures and zero errors.
