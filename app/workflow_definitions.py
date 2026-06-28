from __future__ import annotations

from dataclasses import dataclass

from app.workflow_functions import AVAILABLE_WORKFLOW_FUNCTIONS


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
    # spec phase
    "prepare_project": "prepare_project",
    "generate_spec": "generate_spec",
    "validate_spec": "generate_spec",
    "review_spec": "generate_spec",
    "spec_gate": "generate_spec",

    # todo phase
    "generate_todo": "generate_todo",
    "validate_todo": "generate_todo",
    "review_todo": "generate_todo",
    "todo_gate": "generate_todo",

    # later phases
    "generate_tests": "generate_tests",
    "build": "build",
    "run_test": "build",
    "final_review": "final_review",
    "final_gate": "final_review",
}


USER_QUESTION_ALLOWED_STEPS = {"prepare_project", "generate_spec", "repair_spec"}


CONTEXT_ARTIFACTS_BY_STEP = {
    "review_spec": ["spec.md"],
    "generate_todo": ["spec.md", "spec-review.md"],
    "validate_todo": ["spec.md", "todo.md"],
    "review_todo": ["spec.md", "spec-review.md", "todo.md"],
    "generate_tests": ["spec.md", "todo.md", "todo-review.md"],
    "build": ["spec.md", "spec-review.md", "todo.md", "todo-review.md", "test-plan.md"],
    "run_test": ["test-plan.md", "build-result.md"],
    "final_review": ["spec.md", "todo.md", "test-plan.md", "build-result.md", "test-result.md"],
}


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
        "agent": "qwen" if step.kind == "qwen" else "",
        "provider": "qwen" if step.kind == "qwen" else "",
        "templateContent": "",
        "sources": [],
        "contextArtifacts": CONTEXT_ARTIFACTS_BY_STEP.get(step.key, []),
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

