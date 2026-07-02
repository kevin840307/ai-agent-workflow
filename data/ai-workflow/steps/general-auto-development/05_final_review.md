Perform the final workflow review.

Requirement:
{{requirement}}

Architecture:
{{architecture}}

Todo:
{{todo}}

Build result:
{{build_result}}

Test result:
{{test_result}}

External validation result:
{{external_validation_result}}

Failure feedback:
{{failure_feedback}}

Return only Markdown with this exact structure:

# Final Review

Status: PASS or FAIL
Confidence: 0.00-1.00

## Summary
- ...

## Verification
- Automated test result:
- External validation script result:
- Requirement coverage:
- Architecture alignment:
- Files stayed inside Project path:

## Remaining Risks
- ...

Status must be PASS only when the automated test result and external validation result both passed, and the implementation clearly satisfies the current requirement.
