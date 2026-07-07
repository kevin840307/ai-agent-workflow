id: regression-test-case-generation
name: Regression Test Case Generation
description: 'Generate a reviewable regression test package from SOP/Block/AC context: context, SOP SQL, runtime SQL, expected result, validation.py, markdown case, dry-run report, and final gate.'
kind: system
active: true
protected: true
deletable: false
skillRoot: .ai-workflow
promptRoot: steps/
created_at: '2026-07-07T00:00:00+08:00'
updated_at: '2026-07-07T00:00:00+08:00'
steps:
- contract: contracts/regression-test-case-generation/collect_context.yaml
- contract: contracts/regression-test-case-generation/generate_sop_sql.yaml
- contract: contracts/regression-test-case-generation/generate_runtime_sql.yaml
- contract: contracts/regression-test-case-generation/generate_validation.yaml
- contract: contracts/regression-test-case-generation/generate_case_doc.yaml
- contract: contracts/regression-test-case-generation/dry_run.yaml
- contract: contracts/regression-test-case-generation/final_gate.yaml
