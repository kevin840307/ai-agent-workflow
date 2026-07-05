Review and validate the completed project change against the SPEC.

{{thinking_guidance}}
User request:
{{requirement_brief}}

SPEC:
{{spec}}

Task manifest:
{{task_manifest}}

Execution result:
{{auto_generation_result}}

Validation / test result, if any:
{{external_validation_result}}
{{python_gate_result}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Pass only if:
- The project satisfies the SPEC and user request.
- The implementation includes appropriate tests or a clear reason tests are not applicable.
- Existing behavior appears preserved.
- No validation/test result is failing.

Output only:

# AI Review

Status: PASS or FAIL
Confidence: 0.00-1.00

## Findings
- ...

## Test Check
- State whether tests were added/updated/found, or why tests are not applicable.

## Required Fixes
- If FAIL, list concrete repair prompts for the next Execute Prompts retry.
- If PASS, write `None`.
