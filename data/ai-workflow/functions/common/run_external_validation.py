from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

FUNCTION_META = {
    "id": "run_external_validation",
    "label": "Run External Validation.py",
    "description": "Run a mandatory project validation script such as 驗證.py and write output/external-validation-result.md.",
    "ui": {"tabs": ["basic", "retry", "advanced"]},
}

SCRIPT_NAMES = ["驗證.py", "validation.py", "validate.py", "verify.py", "check.py"]
ARGUMENT_ERROR_MARKERS = (
    "unrecognized arguments",
    "unknown option",
    "no such option",
    "usage:",
)


class ExternalValidationError(Exception):
    pass


def run(context: Any, artifact: str | None = None) -> str:
    project_dir = Path(context.project_dir).expanduser().resolve()
    output_dir = Path(context.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = artifact or "external-validation-result.md"
    workspace = Path(context.run.get("workspace") or output_dir.parent).expanduser().resolve()

    configured_script = str(context.run.get("validation_script") or "").strip()
    script = _find_validation_script(project_dir, configured_script)
    if script is None:
        expected = configured_script or ", ".join(SCRIPT_NAMES)
        result = _format_result(
            status="FAIL",
            script="",
            cwd=project_dir,
            command="",
            return_code=None,
            stdout="",
            stderr=f"No validation script found. Expected: {expected}",
        )
        _write(output_dir / artifact_name, result)
        raise ExternalValidationError(f"No validation script found. Expected: {expected}")

    command = [
        sys.executable,
        str(script),
        "--project",
        str(project_dir),
        "--workspace",
        str(workspace),
        "--output",
        str(output_dir),
    ]
    completed = _run(command, project_dir)
    if completed.returncode != 0 and _looks_like_argument_error(completed.stderr):
        command = [sys.executable, str(script)]
        completed = _run(command, project_dir)

    status = "PASS" if completed.returncode == 0 else "FAIL"
    result = _format_result(
        status=status,
        script=_display_script(project_dir, script),
        cwd=project_dir,
        command=" ".join(_quote(part) for part in command),
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    _write(output_dir / artifact_name, result)
    if completed.returncode != 0:
        raise ExternalValidationError(_summary_failure(completed, script))
    return result


def _find_validation_script(project_dir: Path, configured_script: str = "") -> Path | None:
    explicit = configured_script or os.environ.get("AI_WORKFLOW_VALIDATION_SCRIPT") or os.environ.get("VALIDATION_SCRIPT")
    if explicit:
        return _resolve_explicit_script(project_dir, explicit)
    for name in SCRIPT_NAMES:
        candidate = (project_dir / name).resolve()
        if candidate.is_file():
            return candidate
    return None


def _resolve_explicit_script(project_dir: Path, value: str) -> Path | None:
    raw = Path(value).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (project_dir / raw).resolve()
    if candidate.suffix.lower() != ".py":
        raise ExternalValidationError(f"Validation script must be a Python file: {value}")
    if not candidate.is_file():
        return None
    return candidate


def _inside(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _display_script(project_dir: Path, script: Path) -> str:
    try:
        return str(script.relative_to(project_dir))
    except ValueError:
        return str(script)


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=None)


def _looks_like_argument_error(stderr: str) -> bool:
    lower = (stderr or "").lower()
    return any(marker in lower for marker in ARGUMENT_ERROR_MARKERS)


def _format_result(
    *,
    status: str,
    script: str,
    cwd: Path,
    command: str,
    return_code: int | None,
    stdout: str,
    stderr: str,
) -> str:
    return "\n".join(
        [
            "# External Validation Result",
            "",
            f"Status: {status}",
            f"Script: {script or 'NONE'}",
            f"Cwd: {cwd}",
            f"Command: {command or 'NONE'}",
            f"Exit Code: {return_code if return_code is not None else 'N/A'}",
            "",
            "## Stdout",
            "```",
            (stdout or "").rstrip(),
            "```",
            "",
            "## Stderr",
            "```",
            (stderr or "").rstrip(),
            "```",
            "",
        ]
    )


def _summary_failure(completed: subprocess.CompletedProcess[str], script: Path) -> str:
    transcript = "\n".join(part.strip() for part in [completed.stdout, completed.stderr] if part and part.strip())
    if not transcript:
        transcript = f"{script.name} exited with code {completed.returncode}"
    return f"External validation failed ({script.name}, exit {completed.returncode}): {transcript[:1200]}"


def _quote(value: str) -> str:
    return f'"{value}"' if any(ch.isspace() for ch in value) else value


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="")
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--artifact", default="external-validation-result.md")
    args = parser.parse_args()

    class Context:
        project_dir = Path(args.project)
        output_dir = Path(args.output)
        run = {"workspace": args.workspace or str(Path(args.output).parent)}

    try:
        run(Context(), args.artifact)
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
