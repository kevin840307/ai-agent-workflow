# AI Workflow MVP Mode

`testllm` now supports an `.ai-workflow` filesystem mode inspired by `ai-workflow-mvp` while keeping the UI separate from the storage layout.

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
Project assets are resolved before global assets, so a project can override a shared step, contract, validator, or workflow without changing code.

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
skill: steps/generate_spec.md
type: ai
agent: qwen
retry: 2
outputs:
  - spec.md
validator: validators/validate_spec.py
timeout: 600
approval: false
allowInteraction: true
```

The UI can edit Skill Path, Metadata Path, Python Validator, upload Python assets, or save new skill/metadata files. Manual file changes are picked up automatically by the asset API and workflow list.

## Agent Providers

Built-in providers still include `qwen` and `opencode`. Additional CLI agents can be added in `data/settings.json` without modifying runner code:

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

`type: cli` is the generic provider for future CLI-based agents. Supported prompt modes are `stdin`, `last_arg`, and `prompt_flag`.

## Maintenance Rule

To add a new workflow manually, add files only under `.ai-workflow` or `data/ai-workflow`:

1. Add `steps/*.md` for prompt-only skill content.
2. Add `contracts/*.yaml` for execution metadata.
3. Add `validators/*.py` or `tools/*.py` when Python validation/tooling is needed.
4. Add `workflows/*.workflow` to compose the ordered steps.

No Python or UI code change is required for normal workflow, skill, metadata, or validator additions.
