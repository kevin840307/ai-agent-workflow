# V21 Semantic Hardcode Audit

## Verdict

**PASS for production routing and Artifact presentation.**

No production path classifies free-form user requirement/comment text or user-controlled filenames/paths to decide intent, risk, complexity, scope, Workflow phase, Session role, validation role, Artifact role, or repair target.

## Audited areas

- request/run creation and delivery policy;
- Workflow phase/session/evidence selection;
- Patch Review and rejection routing;
- Validation Evidence Center;
- Artifact backend indexing and frontend grouping/sorting;
- Validation Script expected file/symbol contracts;
- Regression CaseId handling;
- real Agent smoke/E2E routing.

## Explicit contracts used instead

- `phase`
- `sessionRole`
- `evidenceCategory`
- `required` / `blocksApply`
- `workflowInputs.caseId`
- `expectedFiles` / `expectedSymbols`
- `category` / `role` / `visibility`
- `displayOrder` / `producerStepKey` / `mediaType`
- rejection `reasonCode` / explicit retry Step
- Patch, Selection, File, and Evidence hashes

## Artifact rule

`artifact_visibility()` accepts a legacy path parameter only for API compatibility and deliberately ignores it. Artifact classification comes from explicit metadata. Controller-owned exact paths may map known system artifacts to contracts; arbitrary user/Agent paths fall back to `unclassified` and are never keyword-classified.

## Allowed non-semantic parsing

The following are intentionally retained because they validate machine structure rather than infer natural-language meaning:

- exact YAML/JSON fields and enum values;
- exact Controller-owned Artifact paths;
- file extensions for media type and project tool discovery;
- conventional test-file discovery for running a project’s test system;
- compiler/test-runner output parsing;
- protocol error codes and tool event types;
- safety validation for absolute paths, parent traversal, and project boundaries.

These rules do not alter Workflow intent based on user prose.

## Automated evidence

- `tests/test_v21_patch_review_artifacts.py`: explicit metadata, no filename semantics, evidence-bound approval, Partial Patch revalidation, UI contracts, bounded rendering, remembered layout, and storage summary.
- `tests/test_static_architecture_contract.py`: every frontend `ui.byKey()` reference is registered.
- Full isolated matrix: 59/59 files, 728 tests, 0 failures/errors.
- Static browser smoke verifies absence of Changes tab and duplicate diagnostics Patch UI.

## Exclusions

- `app/testing` contains deterministic Mock Agent behavior used only by tests; it is not production routing.
- Natural-language display labels are UI text, not semantic classifiers.
- OS-level Agent sandboxing was not requested for this release and is outside this audit.
