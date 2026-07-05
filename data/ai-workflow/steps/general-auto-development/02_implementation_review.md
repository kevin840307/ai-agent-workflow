Review the completed SOP development result against the SPEC and TODO.

User request:
{{requirement_brief}}

SPEC:
{{spec}}

TODO / task plan:
{{todo}}

Task manifest:
{{task_manifest}}

Task execution result:
{{build_result}}

External validation result, if any:
{{external_validation_result}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Pass only if:
- The project result satisfies the user request and SPEC acceptance criteria.
- The task loop completed the TODO scope or has a clear justified reason for skipped items.
- Tests exist or there is a clear reason tests are not applicable.
- Existing behavior appears preserved.
- No visible validation result is failing.

Output only:

# Implementation Review

Status: PASS or FAIL
Confidence: 0.00-1.00

## Findings
- ...

## Test Check
- State whether tests were added/updated/found, or why tests are not applicable.

## Required Fixes
- If FAIL, list concrete repair prompts for the next Execute Task Loop retry.
- If PASS, write `None`.
