Repair `output/todo.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask questions.
Use a deterministic format: no title before the first `##` heading, no extra sections, no timestamps, no conversational text.

Spec:
{{spec}}

Current Todo:
{{todo}}

Validation Failure:
{{failure_feedback}}

Rewrite the todo with exactly these section headings, in this exact order:

## Todo List
## Test Plan
## Done Criteria

It must include TODO-001, TEST-001, and reference every AC ID from the spec.
Use stable sequential TODO IDs and TEST IDs. Every AC ID must appear in Todo List and Test Plan.
