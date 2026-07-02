# General Auto Development Workflow Usage

This workflow is designed for one-shot automated implementation from a short user requirement.
It supports Web UI, API, and CLI usage with the same backend runtime.

## What It Does

1. Reads the selected project and writes or updates `architecture.md`.
2. Plans small tasks with acceptance criteria in `todo.md`.
3. Reviews the task plan before building.
4. Builds production files inside the selected Project Path.
5. Runs a mandatory Python validation script.
6. Sends validation failures back to Build for retry.
7. Performs final review and requires `Status: PASS`.

The workflow id is:

```text
general-auto-development
```

## Web UI

1. Open the runner page.
2. Select a project.
3. Select `General Auto Development`.
4. Enter the requirement.
5. Optional: fill `Validate` with a Python validation script path.
6. Press `Run`.

Validation script examples:

```text
tools/check_config.py
C:\Users\kevin\validators\check_config_diff.py
```

If `Validate` is empty, the workflow searches the project root for:

```text
驗證.py
validation.py
validate.py
verify.py
check.py
```

## CLI

Auto CLI shortcut:

```powershell
aiwf C:\my-project --engine auto --user "製作config驗證小工具" --workflow general-auto-development --validation-script tools\check_config.py
```

Standard CLI form:

```powershell
aiwf run "製作config驗證小工具" --project C:\my-project --workflow general-auto-development --validation-script tools\check_config.py
```

Qwen/OpenCode slash-command template shown in Workflow Designer:

```text
/wf <target> --user "需求"
```

Those slash-command forms are templates for agent-side command integrations. The backend workflow path is still the same: project path, workflow id, user requirement, and optional validation script.

## API

```http
POST /api/sessions/{session_id}/workflow-runs
Content-Type: application/json
```

```json
{
  "workflow_id": "general-auto-development",
  "requirement": "製作config CRUD小工具",
  "validation_script": "tools/check_config.py"
}
```

## Validation Script Contract

The validation script must be a Python file.

It can be:

- Project-relative, such as `tools/check_config.py`
- Absolute, such as `C:\Users\kevin\validators\check_config.py`

The workflow runs it with Python and passes:

```text
--project <project-path>
--workspace <run-workspace>
--output <run-output-dir>
```

If the script does not accept those arguments, the workflow retries the script without arguments.

Exit code behavior:

- `0`: validation passes
- non-zero: validation fails, writes `output/external-validation-result.md`, and retries from Build

## Project Agent Settings

Agents run with the selected Project Path as cwd.

Project-local files can be used by the agent:

```text
my-project\.qwen\settings.json
my-project\opencode.json
```

Generated file edits are still constrained to the selected Project Path.
