Create a practical implementation task plan.

Requirement:
{{requirement}}

Architecture:
{{architecture}}

Project profile:
{{project_profile}}

Validation script for this run:
{{validation_script}}

Guidance:
{{guidance}}

Failure feedback:
{{failure_feedback}}

Planning rules:
- Do not ask the user questions unless the requirement has no actionable task at all.
- Use reasonable defaults for minor missing details and record them in the plan.
- Split the work into small tasks, but do not over-split. Prefer 3 to 8 tasks, and never more than 12 unless the request is truly large.
- Every task must have clear acceptance criteria.
- Build production changes before Generate Tests so the model does not mix test blocks into Build.
- Include a focused automated test strategy after Build and before external validation.
- Include validation coverage for the user-provided validation script.
- Keep TODO content concise and actionable.
- If multiple TODO files would help, list the recommended file names, but keep this step output in `todo.md`.
- Do not invent a new architecture when the project already has one.

Output only Markdown with this exact structure:

# Todo

Status: READY

## Requirement
- ...

## Task Index
| ID | Task | Acceptance Criteria |
| --- | --- | --- |
| TASK-001 | ... | AC-001 |

## Tasks

### TASK-001: ...
- Goal:
- Files:
- Acceptance Criteria:
  - AC-001:
- Validation:
  - Covered by Build, Generate Tests, Run Test, and the mandatory external validation step.

## Execution SOP
- Step 1: Build production code only.
- Step 2: Generate tests only under the project test folder.
- Step 3: Run automated tests.
- Step 4: Run mandatory external validation script.
- Step 5: Retry Build with concrete failure feedback when tests or validation fail.

## External Validation
- If a validation script path is provided above, that exact script is mandatory for this run.
- If no validation script path is provided, fallback script names are: `驗證.py`, `validation.py`, `validate.py`, `verify.py`, `check.py`
- The workflow must stop if no validation script exists.
- The workflow must run automated tests before this external validation step.
- The workflow must retry Build when tests or validation fail.

## Assumptions
- Use the detected project language and structure.
- Use standard implementation details when the requirement does not specify minor choices.

## Suggested Todo Files
- None unless the task is large enough to benefit from split TODO files.
