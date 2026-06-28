You are generating the workflow artifact `output/todo.md`.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask the user questions.

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

Use exactly these section headings:

## Todo List
- TODO-001: ...

## Test Plan
- TEST-001: ...

## Done Criteria
- Reference all AC IDs explicitly.
