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
