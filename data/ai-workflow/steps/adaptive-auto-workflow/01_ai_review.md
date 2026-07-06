Review the completed project change against the SPEC after the controller has already run validation/test gates.

{{thinking_guidance}}
User request:
{{requirement_brief}}

SPEC:
{{spec}}

Task manifest:
{{task_manifest}}

Execution result:
{{auto_generation_result}}

Validation/test result:
{{external_validation_result}}
{{python_gate_result}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Pass only if:
- The project satisfies the SPEC and user request.
- Tests exist, or tests are clearly not applicable for this request.
- The validation/test result above is PASS or skipped for a valid reason.
- Existing behavior appears preserved.

Return ONLY a JSON object in this shape:
{
  "status": "PASS or FAIL",
  "confidence": 0.0,
  "summary": "one short sentence",
  "missing_items": ["concrete missing item, empty when PASS"],
  "test_check": "tests present / validation passed / tests not applicable because ...",
  "repair_prompt": "concrete prompt for Execute Prompts retry, or empty when PASS"
}
