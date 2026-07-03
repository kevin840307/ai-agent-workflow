# General Auto Development Workflow Usage

This workflow turns a short requirement into project changes with an optional or required Python validation step.
It uses the same backend path from the Web UI, API, and CLI, so Qwen and OpenCode runs share the same workflow behavior.

## Workflow Id

```text
general-auto-development
```

## What It Does

1. Reads the selected project and writes or updates `architecture.md`.
2. Plans small tasks with acceptance criteria in `todo.md`.
3. Reviews the task plan before building.
4. Builds production files inside the selected Project Path.
5. Generates focused tests under `tests/`.
6. Runs automated tests.
7. Runs the configured Python validation script, or a project-root fallback script when present.
8. Sends test or validation failures back to Build for retry.
9. Performs final review and requires `Status: PASS`.

## Web UI

1. Open the runner page.
2. Select a project.
3. Select `General Auto Development`.
4. Enter the user requirement.
5. Optional: fill `Validation Script` with a Python validation script path.
6. Press `Run`.

Validation script examples:

```text
tools/check_config.py
C:\Users\kevin\validators\check_config_diff.py
```

If `Validation Script` is empty, the workflow searches the project root for these portable default names:

```text
validation.py
validate.py
verify.py
check.py
```

## CLI

Auto CLI shortcut:

```powershell
python -m app.cli.aiwf . --engine auto --user "build a config validation tool" --workflow general-auto-development --validation-script tools\check_config.py
```

Standard CLI form:

```powershell
aiwf run "build a config validation tool" --project C:\my-project --workflow general-auto-development --validation-script tools\check_config.py
```

Qwen/OpenCode slash-command template shown in Workflow Designer:

```text
/wf --engine qwen --workflow general-auto-development --user "requirement"
```

Those slash-command forms are templates for agent-side command integrations.
The backend workflow path is still the same: project path, workflow id, user requirement, and optional validation script.

## API

```http
POST /api/sessions/{session_id}/workflow-runs
Content-Type: application/json
```

```json
{
  "workflow_id": "general-auto-development",
  "requirement": "build a config CRUD tool",
  "validation_script": "tools/check_config.py"
}
```

## Validation Script Contract

The validation script must be a Python file. It can be project-relative or absolute:

```text
tools/check_config.py
C:\Users\kevin\validators\check_config.py
```

### Execution Directory

The workflow executes the script with `cwd` set to the selected Project Path.
That means relative file reads and writes inside the script are relative to the project root.

### Inputs Passed by the Workflow

The preferred contract is argparse-style flags:

```text
--project <project-path>
--workspace <run-workspace>
--output <run-output-dir>
```

The workflow command is equivalent to:

```powershell
python <validation-script> --project <project-path> --workspace <run-workspace> --output <run-output-dir>
```

If the script does not accept those flags and fails with an argument-usage error, the runtime retries it without arguments for backward compatibility:

```powershell
python <validation-script>
```

### Output Contract

The most convenient validation output is exit code based:

- exit code `0`: validation passes
- non-zero exit code: validation fails and the workflow retries from Build

The script may use any of these styles:

- `assert` statements
- `raise SystemExit(1)` or `sys.exit(1)` on failure
- `print(...)` for human-readable diagnostics
- output files for detailed evidence

The workflow captures stdout, stderr, command, cwd, script path, and exit code into:

```text
<run-workspace>/output/external-validation-result.md
```

### Path Inputs for Generated Artifacts

For most validators, pass or infer paths in this order:

1. Use `--project` as the project root.
2. Use known filenames from the requirement or project config when the validator has a fixed target.
3. Use `--output` only for workflow-run artifacts, such as writing a detailed validation report.
4. Use `--workspace` only when the validator needs access to the whole run workspace.

Recommended pattern: make the validator accept `--project`, plus optional domain-specific flags such as `--source`, `--expected`, or `--target` when needed. The workflow currently passes the three standard flags automatically; domain-specific filenames can come from the validator defaults or project config.

## Simple Validation Script Example

This validator checks a generated Python module and relies only on exit code, asserts, and stdout.

```python
from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=".")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = Path(args.project).resolve()
    target = project / "calculator.py"

    assert target.is_file(), "calculator.py was not generated"
    text = target.read_text(encoding="utf-8")
    assert "def add" in text, "calculator.py must define add"

    print("validation ok: calculator.py defines add")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Advanced Validation Script Example

This validator checks config before/after output and writes a detailed report into the workflow output directory.

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=".")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--source", default="config/users.yaml")
    parser.add_argument("--target", default="generated/users.yaml")
    return parser.parse_args()


def load_yaml(path: Path):
    if not path.is_file():
        raise AssertionError(f"missing file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    project = Path(args.project).resolve()
    output_dir = Path(args.output).resolve() if args.output else project

    source_path = project / args.source
    target_path = project / args.target
    source = load_yaml(source_path)
    target = load_yaml(target_path)

    users = target.get("users", []) if isinstance(target, dict) else []
    by_id = {item.get("id"): item for item in users if isinstance(item, dict)}

    checks = [
        ("source exists", source_path.is_file()),
        ("target exists", target_path.is_file()),
        ("bob updated to admin", by_id.get("bob", {}).get("role") == "admin"),
        ("carol created", "carol" in by_id),
        ("legacy deleted", "legacy" not in by_id),
    ]

    report = ["# Validation Detail", ""]
    failed = []
    for name, ok in checks:
        report.append(f"- {'PASS' if ok else 'FAIL'}: {name}")
        if not ok:
            failed.append(name)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "validation-detail.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    if failed:
        print("validation failed: " + ", ".join(failed), file=sys.stderr)
        return 1

    print("validation ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Project Agent Settings

Agents run with the selected Project Path as cwd.

Project-local files can be used by the agent:

```text
my-project\.qwen\settings.json
my-project\opencode.json
```

Generated file edits are still constrained to the selected Project Path.
