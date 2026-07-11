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
- Tests exist, or tests are clearly not applicable for this request.
- Existing behavior appears preserved.
- No visible validation result is failing.

Return ONLY a JSON object in this shape:
{
  "status": "PASS or FAIL",
  "confidence": 0.0,
  "summary": "one short sentence",
  "criteria": [{"criterion": "acceptance item", "status": "PASS or FAIL", "evidence": "test/artifact/file evidence"}],
  "missing_items": ["concrete missing item, empty when PASS"],
  "test_check": "tests present / validation passed / tests not applicable because ...",
  "repair_prompt": "concrete prompt for Execute Task Loop retry, or empty when PASS"
}
