Create a concise task plan for this project request.

User request:
{{requirement_brief}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Validation script, if provided:
{{validation_script}}

Retry feedback, if any:
{{latest_failure_feedback}}

Rules:
- Do not implement code in this step.
- Do not explain the workflow platform.
- Plan only the user's project change.
- Keep tasks small enough for a CLI agent to execute, but do not over-split.
- Existing validation scripts are read-only acceptance tools unless the user explicitly asked to edit them.
- If retry feedback exists, update the plan to fix that concrete failure.

Output Markdown only:

# Todo

Status: READY

## Task Index
| ID | Task | Acceptance Criteria | Depends On |
| --- | --- | --- | --- |
| TASK-001 | ... | ... | None |

## Notes
- Testing / validation expectation:
- Assumptions:
