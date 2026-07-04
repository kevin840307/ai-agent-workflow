# Workflow Metadata

Workflow metadata is stored in:

```text
data/ai-workflow/workflows/*.workflow
<project>/.ai-workflow/workflows/*.workflow
```

## Important fields

```yaml
id: adaptive-auto-workflow
name: Adaptive Auto Workflow
description: Simple generate / review / validation loop
kind: system
protected: true
deletable: false
active: false
```

| Field | Behavior |
|---|---|
| `id` | Stable workflow id used by UI, API, and CLI |
| `name` | Display name in the workflow list |
| `description` | Long description shown in details, not in the compact sidebar list |
| `kind` | `system` puts the workflow in the System list |
| `protected` | `true` makes the workflow read-only in UI and API |
| `deletable` | `false` prevents delete in UI and API |
| `active` | Display state only; inactive workflows can still be listed and duplicated |
| `steps` | Step contract references |

## System workflow behavior

A workflow is treated as read-only when any of these conditions is true:

- `id: system-controlled-qwen`
- `kind: system`
- `protected: true`
- `deletable: false` for destructive operations

System workflows appear in the System section. They can be viewed and duplicated, but cannot be edited or deleted directly.

## Custom workflow behavior

Custom workflows are editable unless protected metadata is set. A protected custom file is still shown as read-only.
