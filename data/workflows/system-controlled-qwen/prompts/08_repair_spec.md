Repair `output/spec.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Use a deterministic format: no title before the first `##` heading, no extra sections, no timestamps, no conversational text.

Requirement:
{{requirement}}

Current Spec:
{{raw_spec}}

Validation Failure:
{{failure_feedback}}

Rewrite the spec with exactly these section headings, in this exact order:

## Goal
## Scope
## Out of Scope
## Input
## Output
## Rules
## Acceptance Criteria
## Unknowns

Acceptance Criteria must include AC-001.
All sections must contain at least one bullet. Keep AC IDs stable if the current spec already has valid AC IDs.
