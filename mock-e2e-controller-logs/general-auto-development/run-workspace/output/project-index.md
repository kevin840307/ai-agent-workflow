# Project Index

Status: READY

## Project Path
- /mnt/data/mock-e2e-controller-logs/projects/general-auto-development

## Deterministic Profile
Detected project profile:
- Dominant source extensions: .py (2), .md (1)
- Test framework: pytest, unittest
- Marker/config files: none detected
- Source roots by usage: . (1)
- Existing source files: workflow_mock_feature.py
- Existing test files: tests/test_workflow_mock_feature.py
- Architecture guidance: extend the dominant existing language, module layout, naming, and test style. Do not introduce a new src/tests layout unless it is the dominant source root or architecture.md says to use it.

## Suggested Test Commands
- `python -m pytest`

## Workspace Isolation
- Agent writes must stay inside Project Path.
- External paths may be read as context but are not write targets.
- Protected write directories: `.git`, `.ai-workflow`, `.qwen-workflow`

## Visible Files
- README.md
- tests/test_workflow_mock_feature.py
- workflow_mock_feature.py
