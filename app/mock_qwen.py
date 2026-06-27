from __future__ import annotations


def mock_qwen_response(prompt: str) -> str:
    if "OUTPUT_FILE: output/spec.md" in prompt:
        return """# Spec

## Goal
Build a ChatGPT-like workflow console controlled by a Python runner and powered by Qwen CLI.

## Scope
- Session creation and selection.
- Requirement capture.
- Per-run workspace creation.
- Qwen spec, review, todo, build, and final review steps.
- Python validation, gates, tests, logs, and artifacts.

## Out of Scope
- RBAC.
- Celery, Redis, or distributed queues.
- Vector database and project indexing.
- Git pull request automation.

## Input
- User requirement text.
- Prompt templates.
- Existing source files in the workspace.

## Output
- requirement.md
- spec.md
- todo.md
- review artifacts
- build-result.md
- test-result.md
- final-review.md

## Rules
- Python owns workflow state, validation, gates, and test execution.
- Qwen produces AI-authored artifacts only.
- Failed gates stop later workflow steps.

## Acceptance Criteria
- AC-001 User can create a session.
- AC-002 User can submit a requirement.
- AC-003 Starting a workflow creates a per-run workspace.
- AC-004 Python calls Qwen to generate spec.md.
- AC-005 Python validates spec.md.
- AC-006 Qwen reviews spec.md.
- AC-007 Non-PASS spec review fails the workflow.
- AC-008 Python calls Qwen to generate todo.md.
- AC-009 Python validates todo.md.
- AC-010 Qwen reviews todo.md.
- AC-011 Non-PASS todo review fails the workflow.
- AC-012 Qwen performs the build step.
- AC-013 Non-DONE build result fails the workflow.
- AC-014 Python runs tests.
- AC-015 Test failure fails the workflow.
- AC-016 Qwen performs final review.
- AC-017 Non-PASS final review fails the workflow.
- AC-018 Web UI displays step status.
- AC-019 Web UI displays logs.
- AC-020 Web UI displays artifacts.

## Unknowns
- Exact production authentication model.
- Exact repository test command.
"""
    if "OUTPUT_FILE: output/todo.md" in prompt:
        return """# Todo

## Todo List
- TODO-001 Implement session APIs for AC-001 and AC-002.
- TODO-002 Create run workspaces for AC-003.
- TODO-003 Implement Qwen spec/review/todo/build/final-review calls for AC-004, AC-006, AC-008, AC-010, AC-012, AC-016.
- TODO-004 Implement Python validators and gates for AC-005, AC-007, AC-009, AC-011, AC-013, AC-017.
- TODO-005 Implement Python test execution for AC-014 and AC-015.
- TODO-006 Implement UI status, logs, and artifacts for AC-018, AC-019, AC-020.

## Test Plan
- TEST-001 Verify session creation covers AC-001.
- TEST-002 Verify requirement messages cover AC-002.
- TEST-003 Verify workspace creation covers AC-003.
- TEST-004 Verify workflow artifacts and gates cover AC-004 through AC-017.
- TEST-005 Verify UI data endpoints cover AC-018 through AC-020.

## Done Criteria
- A user can create a session, submit a requirement, start a workflow, inspect live logs, see step statuses, and read artifacts.
- Every acceptance criterion has at least one todo and one test reference.
"""
    if "OUTPUT_FILE: output/architecture.md" in prompt:
        return """Status: DONE

FILE: architecture.md
CONTENT:
# Architecture

## Overview
Mock architecture summary.

## Project Structure
- Source files live in the project root.

## Update Notes
- Generated in mock mode.
END_FILE
"""
    if "OUTPUT_FILE: output/build-result.md" in prompt:
        return "Status: DONE\n\nBuild step completed. In mock mode no source files were modified."
    if "OUTPUT_FILE: output/test-plan.md" in prompt:
        return """Status: DONE

FILE: tests/test_workflow_mock.py
CONTENT:
def test_mock_workflow_placeholder():
    assert True
END_FILE
"""
    if "OUTPUT_FILE: output/final-review.md" in prompt:
        return "Status: PASS\n\nFinal review passed in mock mode."
    return "Status: PASS\n\nReview passed in mock mode."
