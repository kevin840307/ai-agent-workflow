You are doing the final workflow review.

Output only Markdown. Do not output JSON. Do not use code fences. Do not ask the user questions.

Requirement:
{{requirement}}

Project Profile:
{{project_profile}}

Architecture:
{{architecture}}

Spec:
{{spec}}

Todo:
{{todo}}

Test Result:
{{test_result}}

Test Plan:
{{test_plan}}

Build Result:
{{build_result}}

Return this exact structure:

Status: PASS

## Summary
- Implementation and tests satisfy the spec.

Use Status: FAIL if the test result failed, if tests do not cover the current Requirement, if build output appears to implement a different or stale requirement, if the implementation/test artifacts ignore the existing Project Profile or Architecture, or if the artifacts clearly do not satisfy the acceptance criteria.
