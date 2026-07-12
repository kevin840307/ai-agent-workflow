# Workflow and Asset Development

## Asset layout

```text
data/ai-workflow/
  workflows/*.workflow
  contracts/<workflow>/*.yaml
  steps/<workflow>/*.md
  functions/<workflow>/*.py
```

Project overrides live under `<project>/.ai-workflow/` and take precedence over global assets.

## Design rules

- Prompts instruct Qwen/OpenCode; they do not contain generated project files.
- Python functions validate, route, summarize, or protect; they do not implement the user’s requested product behavior.
- Contracts declare timeout, retry, recovery budget, review mode, validation requirements, and artifacts.
- Keep task prompts short and natural. Do not emit shell scripts, absolute paths, code blocks, FILE blocks, or tool-call JSON.
- Add a deterministic test for every new failure route or completion requirement.

## Recovery budget example

```yaml
maxRetries: 99
recoveryBudget:
  maxRunFailures: 40
  maxStepFailures: 24
  maxTaskFailures: 12
  maxFailureClass: 12
  maxFingerprint: 9
  wallClockMinutes: 60
  freshSessionEvery: 3
```

`maxRetries` permits small-model recovery; the cumulative budget prevents infinite work.

## Task acceptance example

```json
{
  "id": "TASK-001",
  "title": "Update configuration loading",
  "kind": "implementation",
  "prompt": "Update the existing configuration loader and preserve current public behavior.",
  "acceptance": ["Existing and new tests pass"],
  "scope": ["src/config/**", "tests/config/**"],
  "mustNotChange": ["validation.py"],
  "dependencies": [],
  "risk": "normal"
}
```

Only include file constraints supported by actual project evidence. The controller must not invent implementation paths.
