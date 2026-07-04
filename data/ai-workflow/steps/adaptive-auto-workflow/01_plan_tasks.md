Create a practical implementation task plan.

Requirement:
{{requirement}}

Architecture:
{{architecture}}

Project index:
{{project_index}}

Project profile:
{{project_profile}}

Validation script for this run:
{{validation_script}}

Fallback validation scripts configured by this workflow:
{{fallback_validation_scripts}}

Guidance:
{{guidance}}

Failure feedback:
{{failure_feedback}}

Planning rules:
- Do not ask the user questions unless the requirement has no actionable task at all.
- User instructions and provided config files are the source of truth. Follow explicit user-provided steps, file paths, formats, and validation expectations before applying defaults.
- If the user restricts allowed tools, libraries, commands, languages, or frameworks, preserve those restrictions in the plan and do not substitute alternatives.
- Use reasonable defaults only for minor missing details and record them in the plan.
- Split the work into small tasks, but do not over-split. Prefer 3 to 8 tasks, and never more than 12 unless the request is truly large.
- Think in layers: small task -> assembled feature -> final completed request.
- Every task must have clear acceptance criteria and an integration/assembly expectation.
- Define explicit stop conditions: the workflow is done only when Build produced project changes, automated tests pass, external validation passes or is intentionally skipped, and final review is PASS.
- Build production changes before Generate Tests so the model does not mix test blocks into Build.
- For any requested generated artifact, include the source inputs, output path, expected format, and verification method in the plan.
- For any requested tool or script, include the executable entry point, supported invocation, input config path(s), scanned directory path(s), and output path(s).
- If the user says the tool must read user-provided config or scan files, plan real file I/O and a CLI-compatible interface. Do not plan simulated in-memory examples.
- Treat configured validation scripts as protected acceptance tools when they already exist or are provided for this run.
- Do not list a validation script under task Files or ask Build to modify it unless the user explicitly asks to create or change that validator itself.
- Include a focused automated test strategy after Build and before external validation.
- Include validation coverage for the user-provided validation script when one is provided.
- Keep TODO content concise and actionable.
- Plan small task TODO files by task ID. This step still outputs only `todo.md`; Python will compile it into `output/todos/TASK-xxx.md` files after review.
- Do not invent a new architecture when the project already has one.

Output only Markdown with this exact structure:

# Todo

Status: READY

## Requirement
- ...

## Task Index
| ID | Task | Acceptance Criteria | Depends On |
| --- | --- | --- | --- |
| TASK-001 | ... | AC-001 | None |

## Task Assembly Plan
- Build order:
- Integration point:
- Assembled behavior that proves the larger request is complete:

## Tasks

### TASK-001: ...
- Goal:
- Files:
- Acceptance Criteria:
  - AC-001:
- Depends On:
  - None
- Assembly:
  - How this task connects to later tasks or the final requested behavior.
- Validation:
  - Covered by Build, Generate Tests, Run Test, and external validation when configured or present.

## Execution SOP
- Step 1: Build production code only.
- Step 2: Generate tests only under the project test folder.
- Step 3: Run automated tests.
- Step 4: Run external validation when a script is configured or present.
- Step 5: Retry the failed owner step with concrete recovery analysis until the stop conditions are met or max retries are reached.

## Acceptance & Stop Conditions
- Build must create or modify at least one production/project artifact under Project path.
- Small tasks must be implemented in order and assembled into one coherent project state.
- Generate Tests must create focused tests for the acceptance criteria and assembled behavior.
- Run Test must pass.
- External validation must pass when configured or present; otherwise it must record a skipped PASS.
- Final Review and Final Gate must both pass.
- Stop retrying when the configured max retry count is reached.

## External Validation
- If a validation script path is provided above, that exact script is mandatory for this run.
- If no validation script path is provided, use only the fallback validation script names configured by this workflow.
- Existing validation scripts are read-only to Build and must be run after automated tests.
- If no validation script is configured or found, external validation is skipped with a PASS result.
- The workflow must run automated tests before this external validation step.
- The workflow must retry Build when tests or validation fail.

## Assumptions
- Use the detected project language and structure.
- Use standard implementation details only when the requirement does not specify minor choices.

## Suggested Todo Files
- output/todos/TASK-001.md
- output/todos/TASK-002.md when a second task exists
- output/todos/TASK-003.md when a third task exists
