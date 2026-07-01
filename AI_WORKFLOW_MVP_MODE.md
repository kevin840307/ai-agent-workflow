# AI Workflow MVP Mode

`testllm` supports an `.ai-workflow` filesystem mode inspired by `ai-workflow-mvp` while keeping the UI independent from the storage layout.

## Directory Layout

```text
.ai-workflow/
  workflows/
    requirement.workflow
  contracts/
    generate_spec.yaml
  steps/
    generate_spec.md
  validators/
    validate_spec.py
  tools/
    helper.py
```

The same layout is supported globally under `data/ai-workflow/` and per project under `<project>/.ai-workflow/`.
Project assets are resolved before global assets, so a project can override a shared step, contract, validator, tool, or workflow without changing code.

## Workflow File

A `.workflow` file is intentionally small and readable:

```text
# workflows/default.workflow
contract: generate_spec
contract: review_spec
step: steps/generate_todo.md
@shared-review
```

Supported lines:

- `contract: name` loads `contracts/name.yaml`.
- `step: steps/name.md` creates an implicit AI step from a pure skill markdown file.
- `workflow: other` or `@other` includes another `.workflow` file.

## Contract Metadata

Skill prompt content and execution metadata are separated:

```yaml
id: generate_spec
name: Generate Spec
skill: steps/generate_spec.md
type: ai
agent: qwen
command: /spec
retry: 2
outputs:
  - spec.md
validator: validators/validate_spec.py
timeout: 600
allowInteraction: false
thinking: false
confidenceThreshold: 0.9
passKeywords: PASS
failKeywords: FAIL
aggregatorFunction: keyword_confidence
failAction: same_step
retryFromStepKey: build
keepSameSession: true
injectFailureFeedback: true
stopAfterFailures: 3
approvalRequired: false
pauseAfterStep: false
approvalMessage: Please review before continuing.
agentOptions:
  model: qwen3-coder
```

Common aliases are also accepted, for example `max_retries`, `confidence_threshold`, `allow_interaction`, `retry_from_step_key`, and `skill_path`.

## UI / CLI Shared Assets

The Workflow Designer has a `.ai-workflow Assets` panel for the same files used by the CLI:

- list global and project-local assets
- create new skill, metadata, Python validator/tool, or `.workflow` file
- read and edit existing files
- upload `.md`, `.yaml`, `.json`, `.py`, or `.workflow` files
- rename or delete assets
- apply a selected skill/metadata/python file to the currently selected step

The CLI uses the same backend resolver:

```bash
python -m app.cli.aiwf assets --project /path/to/project
python -m app.cli.aiwf run "build this" --project /path/to/project --workflow default
```

Manual file changes under `.ai-workflow` or `data/ai-workflow` are visible in UI and CLI after refresh. No Python or UI code change is required for normal workflow, skill, metadata, validator, or tool additions.

## Agent Providers

Built-in providers include `qwen` and `opencode`. Additional CLI agents can be added in `data/settings.json` without modifying runner code:

```json
{
  "agents": {
    "default": "qwen",
    "providers": {
      "qwen": { "type": "qwen_cli", "bin": "qwen" },
      "opencode": { "type": "opencode_cli", "bin": "opencode" },
      "codex": {
        "type": "cli",
        "bin": "codex",
        "promptMode": "stdin",
        "timeoutSec": 1200
      }
    }
  }
}
```

`type: cli` is the generic provider for future CLI-based agents. Supported prompt modes are `stdin`, `last_arg`, and `prompt_flag`. Step metadata may override compatible provider options such as `model`, `timeoutSec`, `thinking`, and `extraArgs`.

## Maintenance Rule

To add a new workflow manually, add files only under `.ai-workflow` or `data/ai-workflow`:

1. Add `steps/*.md` for prompt-only skill content.
2. Add `contracts/*.yaml` for execution metadata.
3. Add `validators/*.py` or `tools/*.py` when Python validation/tooling is needed.
4. Add `workflows/*.workflow` to compose the ordered steps.

Keep skills prompt-only, keep metadata in contracts, and keep executable logic in Python assets. This keeps workflow behavior clear and maintainable.
