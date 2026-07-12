# Validation

## Validation layers

The platform detects and runs a project-native engineering plan:

```text
Build → impacted tests → full tests → lint → type check → configuration checks
→ optional immutable Validation Script → Completion Gate
```

Supported detection includes Python, Maven, Gradle, .NET, Node, YAML/XML, SQL, Docker/Kubernetes, and custom validator plugins. Focused impacted tests accelerate feedback but never replace the full final suite.

## Validation Script contract

A Validation Script is a project-owned, deterministic acceptance oracle. Configure a project-relative path such as `validation.py`.

The controller first runs:

```text
python validation.py --project <project_path> --workspace <run_workspace> --output <output_dir>
```

When the script explicitly rejects these arguments, it falls back to:

```text
python validation.py
```

The script is hashed when the run starts and verified before/after execution. Qwen/OpenCode may read it for acceptance context but must not modify it.

## Complete example

```python
import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--workspace")
    parser.add_argument("--output")
    args = parser.parse_args()

    project = Path(args.project or ".").resolve()
    expected_file = project / "sort_utils.py"

    if not expected_file.exists():
        print(f"FAIL: missing file: {expected_file}")
        return 1

    source = expected_file.read_text(encoding="utf-8")
    if "def bubble_sort" not in source:
        print("FAIL: bubble_sort was not implemented")
        return 1

    print("PASS: validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## Fallback candidates

A contract may define project-relative candidates:

```yaml
fallbackValidationScripts:
  - validation.py
  - validate.py
  - verify.py
  - check.py
```

A missing script is allowed only when the step does not require one. AI review text never overrides a failed deterministic gate.

## Reusable Project Validation Profile

The Validation Script remains the immutable business oracle. The Project Validation Profile is a separate reusable engineering plan for Build/Test/Lint/Type Check and environment preflight.

- It is stored in controller data, not written into the project by default.
- Auto-detection creates `Draft`.
- Successful execution creates `Verified`; three successes create `Trusted`.
- Changes to build/test/validation descriptors create `Stale`.
- Commands run from the effective Project Path cwd.
- Existing failures are captured in baseline; final validation blocks only new/worsened failures plus unmet acceptance criteria.

Advanced users can edit phases/categories/environment/scope as JSON through the Project Validation dialog. Editing resets trust until the profile is verified again.
