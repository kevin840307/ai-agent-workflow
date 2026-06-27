from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    kind: str
    artifact: str | None = None


DEFAULT_WORKFLOW_STEPS = [
    Step("prepare_project", "Prepare Project", "qwen", "architecture.md"),
    Step("generate_spec", "Generate Spec", "qwen", "spec.md"),
    Step("validate_spec", "Validate Spec", "validator"),
    Step("review_spec", "Review Spec", "qwen", "spec-review.md"),
    Step("spec_gate", "Spec Gate", "gate"),
    Step("generate_todo", "Generate Todo", "qwen", "todo.md"),
    Step("validate_todo", "Validate Todo", "validator"),
    Step("review_todo", "Review Todo", "qwen", "todo-review.md"),
    Step("todo_gate", "Todo Gate", "gate"),
    Step("generate_tests", "Generate Tests", "qwen", "test-plan.md"),
    Step("build", "Build", "qwen", "build-result.md"),
    Step("run_test", "Run Test", "test", "test-result.md"),
    Step("final_review", "Final Review", "qwen", "final-review.md"),
    Step("final_gate", "Final Gate", "gate"),
]


SKILLS_BY_STEP = {
    "prepare_project": ["spec-driven-development", "code-review-and-quality"],
    "generate_spec": ["spec-driven-development"],
    "repair_spec": ["spec-driven-development"],
    "review_spec": ["code-review-and-quality", "doubt-driven-development"],
    "generate_todo": ["planning-and-task-breakdown"],
    "repair_todo": ["planning-and-task-breakdown"],
    "review_todo": ["code-review-and-quality", "doubt-driven-development"],
    "generate_tests": ["test-driven-development"],
    "build": ["incremental-implementation"],
    "run_test": ["test-driven-development", "debugging-and-error-recovery"],
    "final_review": ["shipping-and-launch", "code-review-and-quality"],
}


RETRY_FROM = {
    "prepare_project": "prepare_project",
    "validate_spec": "generate_spec",
    "spec_gate": "review_spec",
    "validate_todo": "generate_todo",
    "todo_gate": "review_todo",
    "generate_tests": "generate_tests",
    "build": "build",
    "run_test": "build",
    "final_gate": "final_review",
}


USER_QUESTION_ALLOWED_STEPS = {"prepare_project", "generate_spec", "repair_spec"}


def workflow_step_to_config(step: Step) -> dict:
    step_type = {
        "qwen": "ai",
        "validator": "validation",
        "gate": "gate",
        "test": "python",
    }.get(step.kind, step.kind)
    return {
        "id": f"system-{step.key}",
        "key": step.key,
        "name": step.title,
        "type": step_type,
        "enabled": True,
        "description": "",
        "command": "",
        "templatePath": "",
        "filename": step.artifact or "",
        "outputFile": step.artifact or "",
        "templateContent": "",
        "sources": [],
        "reviewMode": "current_session" if "review" in step.key else "none",
        "reviewers": [],
        "confidenceThreshold": 0.75,
        "passKeywords": "PASS, APPROVED",
        "failKeywords": "FAIL, BLOCKED",
        "aggregatorFunction": "",
        "maxRetries": 2,
        "failAction": "same_step",
        "retryFromStepKey": RETRY_FROM.get(step.key, ""),
        "keepSameSession": True,
        "injectFailureFeedback": True,
        "stopAfterFailures": 3,
        "pauseAfterStep": step.kind == "gate",
        "approvalRequired": step.kind == "gate",
        "approvalMessage": "",
        "timeoutEnabled": False,
        "timeoutMinutes": 0,
        "allowInteraction": step.key in USER_QUESTION_ALLOWED_STEPS,
        "expectedFiles": [step.artifact] if step.artifact else [],
        "validator": {
            "validate_spec": "validate_spec",
            "validate_todo": "validate_todo",
            "spec_gate": "require_status_pass",
            "todo_gate": "require_status_pass",
            "final_gate": "require_status_pass",
            "run_test": "run_pytest",
        }.get(step.key, ""),
    }


def system_workflow_config() -> dict:
    return {
        "id": "system-controlled-qwen",
        "kind": "system",
        "name": "Controlled Qwen Workflow",
        "description": "Built-in protected workflow. Duplicate it to create an editable custom workflow.",
        "active": True,
        "protected": True,
        "deletable": False,
        "skillRoot": str(DEFAULT_SKILL_ROOT_PLACEHOLDER),
        "promptRoot": "prompts/",
        "steps": [workflow_step_to_config(step) for step in DEFAULT_WORKFLOW_STEPS],
    }


DEFAULT_SKILL_ROOT_PLACEHOLDER = "~/.qwen/skills"


AVAILABLE_WORKFLOW_FUNCTIONS = {
    "validators": [
        {
            "id": "validate_spec",
            "label": "Validate Spec",
            "description": "Check required spec sections and AC IDs.",
        },
        {
            "id": "validate_todo",
            "label": "Validate Todo",
            "description": "Check todo sections, TEST IDs, and AC coverage.",
        },
        {
            "id": "require_status_pass",
            "label": "Require Status PASS",
            "description": "Gate helper for review artifacts that must contain Status: PASS.",
        },
        {
            "id": "run_pytest",
            "label": "Run Pytest",
            "description": "Run the configured Python test command.",
        },
    ],
    "reviewStrategies": [
        {
            "id": "current_session",
            "label": "Current Session Review",
            "description": "Reuse the current Qwen session for review.",
        },
        {
            "id": "new_agent",
            "label": "New Agent Review",
            "description": "Run review in a fresh Qwen session.",
        },
        {
            "id": "multi_agent",
            "label": "Multi-Agent Review",
            "description": "Run one or more reviewer agents and aggregate their results.",
        },
    ],
    "aggregators": [
        {
            "id": "keyword_confidence",
            "label": "Keyword + Confidence",
            "description": "Combine pass/fail keywords with a confidence threshold.",
        },
        {
            "id": "majority_vote",
            "label": "Majority Vote",
            "description": "Pass when most reviewers pass.",
        },
        {
            "id": "all_must_pass",
            "label": "All Must Pass",
            "description": "Pass only when every reviewer passes.",
        },
    ],
}
