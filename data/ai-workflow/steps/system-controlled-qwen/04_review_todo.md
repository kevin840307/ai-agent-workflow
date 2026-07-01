You are reviewing `output/todo.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask the user questions.
Use exactly one of the two structures below. Do not add extra sections.

Spec:
{{spec}}

Todo:
{{todo}}

Return this exact structure:

Status: PASS

## Findings
- None.
Confidence: 1.0

If the todo is missing TODO-001, TEST-001, or does not reference every AC ID from the spec, use:

Status: FAIL

## Findings
- Explain the concrete issue to fix.
Confidence: 1.0
