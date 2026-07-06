# Retry Policy

Workflow steps can use a generic retry policy:

```yaml
retryPolicy:
  defaultRetryTo: auto_generation
  escalateEvery: 3
  escalateTo: generate_task_prompts
  maxRetries: 99
```

Normal failures retry the repair target. Every N failures can escalate to an earlier planning step.

Recommended pattern:

- Task failure: retry the same execution step.
- Review failure: retry execution with repair prompt.
- Validation failure: retry execution with validation error.
- Repeated failure: escalate to planning.
