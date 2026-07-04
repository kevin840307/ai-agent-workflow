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
3. Reviews the task plan and generates `output/task-manifest.md` before building.
4. Builds production files inside the selected Project Path using the task order and assembly plan.
5. Generates focused tests under `tests/`.
6. Runs automated tests.
7. Runs the configured Python validation script, or a project-root fallback script when present.
8. Writes structured recovery analysis when a gate fails.
9. Retries the owner step until the acceptance/stop conditions pass or max retries are reached.
10. Performs final review and requires `Status: PASS`.

## Development Loop Contract

The workflow behaves like a small controlled AI development loop:

```text
Requirement
→ Prepare Project
→ Plan Tasks + Acceptance Criteria
→ Generate Task Manifest
→ Build production files by task order
→ Generate focused tests
→ Run tests
→ Run external validation
→ Final Review / Final Gate
```

When a step fails, the runtime writes `input/failure-feedback.md` with:

- failed step
- retry target
- retry count and stop condition
- recovery analysis
- exact error message

The next retry prompt receives only the feedback for that target step, so Build fixes implementation failures, while Generate Tests fixes broken generated tests.

## Acceptance and Stop Conditions

A run is complete only when all of these are true:

- `output/task-manifest.md` exists and records the small-task order.
- Build created or modified at least one production/project artifact under Project Path.
- Generated tests exist.
- Automated tests pass.
- External validation passes when configured or present, or records a skipped PASS when not present.
- Final Review writes `Status: PASS`.
- Final Gate accepts `final-review.md`.

Retries stop when the retry target reaches its configured max retry count. The workflow does not silently generate production files as a fallback when Build fails to output files.

## Hard-Code Policy

General Auto Development must not contain domain-specific production fallbacks.

Allowed generic runtime helpers:

- minimal spec/todo skeleton repair when the agent returns malformed planning artifacts
- generic Python import smoke test when a Python project has production modules but the agent emits no valid tests
- pytest wrapper for a user-provided validation script

Not allowed:

- hard-coded production implementation for sorting, CRUD, config transforms, APIs, UI pages, security scans, or any other specific user requirement
- hidden domain marker lists that infer behavior from keywords
- Build fallback code that materializes requested product files without the agent producing them

## Web UI

`General Auto Development` supports a run-specific validation script through the step-side field.
The field is shown because the workflow's `Run External Validation` step has `Requires Validation Script` enabled.

1. Open the runner page.
2. Select a project.
3. Select `General Auto Development`.
4. Enter the user requirement.
5. In the workflow step preview, find `Run External Validation`.
6. Fill the step-side `Validation Script` field with a Python validation script path, for example `tools/check_config.py`.
7. Press `Run`.

Designer setup note:

- The field appears only when at least one enabled step has `Requires Validation Script` checked.
- For `General Auto Development`, this should be checked on the `Run External Validation` step.
- Do not add a global composer-level validation field; keep the field tied to the step requirement.

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

Generated file edits are still constrained to the selected Project Path. Paths outside Project Path are read-only context.

Runtime isolation rules:

- Agent cwd is the selected Project Path.
- Materialized `FILE/CONTENT/END_FILE` writes are resolved through the platform write guard.
- Python function writes are guarded: workspace output files are allowed, project writes must stay under Project Path.
- Runtime environment variables expose `AI_WORKFLOW_WRITE_ROOT=<project-path>` and `AI_WORKFLOW_WRITE_POLICY=project_only` for agent/provider integrations.
- Absolute paths, `..`, `.git`, `.ai-workflow`, and `.qwen-workflow` are rejected for materialized file blocks.

## Stability Controls Added For Development Use

The workflow is intentionally controlled by Python gates rather than by AI self-declaration.


### Codex / Claude Code Style Control Layer

This workflow intentionally avoids automatic `git commit` / `git push`. The user reviews normal git diff manually.

The closer-to-coding-agent path is now:

```text
Project Index
→ Todo / task-manifest.md
→ Build per-task loop
→ Generate Tests per-task loop
→ Run Test
→ External Python Validation
→ verifier-report.json / diff-context.md
→ Diff Reviewer Agent
→ Final Gate
```

Key rules:

- Build runs build-owned `TASK-xxx` items in order and writes per-task artifacts under `output/tasks/<TASK-ID>/build-result.md`.
- Generate Tests uses the same build task order and writes `output/tasks/<TASK-ID>/test-plan.md`.
- Final Review writes `output/verifier-report.json`; this is the machine-readable source of truth for PASS / FAIL evidence.
- Diff Review is an AI reviewer that may report risks or missing tests, but it cannot decide final PASS.
- Repair feedback includes an error class such as `NO_FILE_OUTPUT`, `TEST_FAILED`, `VALIDATION_FAILED`, or `PATH_VIOLATION`. Repeated errors are allowed until max retry, but after repeated same classes the model is told to switch strategy.

### Deterministic Project Index

Before planning or building, the runner writes:

```text
output/project-index.md
```

This file is generated by Python and includes:

- selected Project Path
- detected language / test framework / source and test files
- suggested test commands
- workspace isolation rules
- visible project files

Agent prompts read this index so later steps do not need to guess the project shape every time.


### Deterministic Task Manifest

`plan_tasks` still uses the agent to understand the requirement, but `implementation_review` now converts the approved `todo.md` into:

```text
output/task-manifest.md
```

The manifest gives later steps a stable small-task order and assembly strategy:

```text
small task → assembled feature → final completed request
```

This keeps the workflow simple while making task splitting more useful for smaller models. Build still runs as one visible step, but it receives the task order, dependencies, and assembly expectations. Generate Tests receives the same manifest and must cover both task-level acceptance criteria and assembled behavior.

### Run Profiles

The run profile is a small runner-level control, not a new workflow step.

```text
fast    fewer retries for quick iteration
normal  default workflow behavior
deep    compatible-agent thinking flag + higher retry budgets
```

CLI example:

```bash
python -m app.cli.aiwf run "add config checker" --project . --workflow general-auto-development --profile deep
```

API request field:

```json
{
  "workflow_id": "general-auto-development",
  "requirement": "add config checker",
  "runProfile": "deep"
}
```

`deep` is useful when the agent supports a thinking/reasoning flag, such as OpenCode. Providers that do not support the flag simply ignore it; validation still depends on Python gates.

### Deterministic Final Verification

The final review is generated from concrete artifacts:

- `output/task-manifest.md`
- `output/build-result.md`
- `output/test-result.md`
- `output/external-validation-result.md`

Final PASS requires:

- Python generated a ready task manifest from `todo.md`.
- Build produced production `FILE/CONTENT/END_FILE` blocks.
- Automated tests passed.
- External validation passed or recorded an intentional skipped PASS.
- Final Gate sees `Status: PASS`.

### Repeated Failure Retry Policy

Repeated errors are still allowed to retry until the configured max retry count. This is intentional because small/local models may produce the same bad shape a few times and then recover after more structured failure feedback.

Typical behavior:

```text
run_test FAIL
→ classify owner as build or generate_tests
→ write structured failure feedback
→ retry owner step
→ if the same failure appears again, log it as repeated but continue until max retries
```

Hard safety failures such as unsafe write paths are still blocked by the workspace guard.
