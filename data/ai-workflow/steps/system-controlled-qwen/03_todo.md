You are generating the workflow artifact `output/todo.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask the user questions.
Use a deterministic format: no title before the first `##` heading, no extra sections, no timestamps, no conversational text.

Requirement:
{{requirement}}

Project Profile:
{{project_profile}}

Architecture:
{{architecture}}

Spec:
{{spec}}

Previous Failure Feedback:
{{failure_feedback}}

Create an implementation todo from the Spec. Reference every AC ID from the spec. Do not introduce a different language/framework than the Requirement, Project Profile, or Architecture implies. If the project already has source files, plan changes in that same module layout.

Use exactly these section headings, in this exact order:

## Todo List
- TODO-001: Implement ... (covers AC-001)

## Test Plan
- TEST-001: Verify ... (covers AC-001)

## Done Criteria
- Reference all AC IDs explicitly.

Rules:
- Use stable sequential TODO IDs and TEST IDs.
- Every AC ID from the spec must appear at least once in Todo List and at least once in Test Plan.
- Keep todo wording concrete and implementation-oriented.
