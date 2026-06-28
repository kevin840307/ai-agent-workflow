You are reviewing `output/spec.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask the user questions.

Requirement:
{{requirement}}

Spec:
{{spec}}

Return this exact structure:

Status: PASS

## Findings
- None.

If the spec is missing required sections, has no AC-001, contradicts the requirement, or asks questions instead of making reasonable assumptions, use:

Status: FAIL

## Findings
- Explain the concrete issue to fix.
