# Workflow Context Dependency Patch

This patch fixes an important runtime behavior: agent steps now receive required artifacts from previous steps even when a custom prompt template forgets to include the matching placeholder.

## What changed

- `generate_todo` receives `spec.md` / `spec-review.md` as required context.
- `generate_tests` receives `spec.md` / `todo.md` / `todo-review.md` as required context.
- `build` receives `spec.md` / `spec-review.md` / `todo.md` / `todo-review.md` / `test-plan.md` as required context.
- `final_review` receives `spec.md` / `todo.md` / `test-plan.md` / `build-result.md` / `test-result.md`.
- Prompt templates were strengthened so Build must follow project language/framework and cannot invent another language.

## New workflow.json field

Each step can now define:

```json
"contextArtifacts": ["spec.md", "todo.md", "test-plan.md"]
```

If omitted, runtime uses a safe built-in default mapping by step key.

## Why

Before this patch, `{{spec}}`, `{{todo}}`, and `{{test_plan}}` were only included when the prompt template explicitly contained the placeholder. Custom workflows could silently drop important context, causing build steps to write unrelated code or another language.
