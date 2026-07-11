from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.workflow_runtime.validation_contract import ValidationContractError, verify_validation_contract

FUNCTION_META = {
    "id": "run_external_validation",
    "label": "Run External Validation",
    "description": "Run an optional user-provided Python validation script and write output/external-validation-result.md.",
    "ui": {"tabs": ["basic", "retry", "advanced"]},
}

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

    contract = context.run.get("validation_contract") if isinstance(getattr(context, "run", None), dict) else None
    configured_script = str(context.run.get("validation_script") or "").strip()
    required = bool((contract or {}).get("required")) or _requires_validation_script(context)
    timeout_seconds = int((contract or {}).get("timeout_seconds") or 300)
    source_hash = str((contract or {}).get("sha256") or "")

    try:
        if contract:
            verified_contract, script = verify_validation_contract(context.run)
            timeout_seconds = int(verified_contract.get("timeout_seconds") or timeout_seconds)
            source_hash = str(verified_contract.get("sha256") or source_hash)
        else:
            fallback_scripts = _fallback_validation_scripts(context)
            script = _find_validation_script(project_dir, configured_script, fallback_scripts)
    except ValidationContractError as exc:
        result = _format_result(
            status="BLOCKED", script=configured_script, cwd=project_dir, command="",
            return_code=None, stdout="", stderr=str(exc), source_hash=source_hash,
        )
        _write(output_dir / artifact_name, result)
        _record_validation(context.run, "BLOCKED", None, str(exc), source_hash=source_hash)
        raise ExternalValidationError(str(exc)) from exc

    if script is None:
        fallback_scripts = _fallback_validation_scripts(context)
        expected = configured_script or ", ".join(fallback_scripts) or "no fallback scripts configured"
        if not required:
            result = _format_result(
                status="NOT_CONFIGURED", script="", cwd=project_dir, command="",
                return_code=None,
                stdout="Optional user validation was not configured. No PASS evidence was fabricated.",
                stderr="", source_hash="",
            )
            _write(output_dir / artifact_name, result)
            _record_validation(context.run, "NOT_CONFIGURED", None, "Optional validation not configured")
            return result
        message = f"VALIDATION_FILE_NOT_FOUND: No validation script found. Expected: {expected}"
        result = _format_result(
            status="BLOCKED", script="", cwd=project_dir, command="",
            return_code=None, stdout="", stderr=message, source_hash=source_hash,
        )
        _write(output_dir / artifact_name, result)
        _record_validation(context.run, "BLOCKED", None, message, source_hash=source_hash)
        raise ExternalValidationError(message)

    command = [
        sys.executable, str(script), "--project", str(project_dir),
        "--workspace", str(workspace), "--output", str(output_dir),
    ]
    try:
        completed = _run(command, project_dir, timeout_seconds=timeout_seconds)
        if completed.returncode != 0 and _looks_like_argument_error(completed.stderr):
            command = [sys.executable, str(script)]
            completed = _run(command, project_dir, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        message = f"External validation timed out after {timeout_seconds} seconds: {script.name}"
        result = _format_result(
            status="ERROR", script=_display_script(project_dir, script), cwd=project_dir,
            command=" ".join(_quote(part) for part in command), return_code=None,
            stdout=str(exc.stdout or ""), stderr=message, source_hash=source_hash,
        )
        _write(output_dir / artifact_name, result)
        _record_validation(context.run, "ERROR", None, message, source_hash=source_hash)
        raise ExternalValidationError(message) from exc

    status = "PASS" if completed.returncode == 0 else "FAIL"
    result = _format_result(
        status=status, script=_display_script(project_dir, script), cwd=project_dir,
        command=" ".join(_quote(part) for part in command), return_code=completed.returncode,
        stdout=completed.stdout, stderr=completed.stderr, source_hash=source_hash,
    )
    _write(output_dir / artifact_name, result)
    _record_validation(
        context.run, status, completed.returncode,
        (completed.stdout or completed.stderr or status)[:4000], source_hash=source_hash,
        command=command,
    )
    if completed.returncode != 0:
        raise ExternalValidationError(_summary_failure(completed, script))
    return result


def _record_validation(
    run: dict[str, Any], status: str, exit_code: int | None, message: str,
    *, source_hash: str = "", command: list[str] | None = None,
) -> None:
    rows = run.setdefault("validation_results", [])
    if not isinstance(rows, list):
        rows = []
        run["validation_results"] = rows
    record = {
        "key": "user_validation",
        "status": status.lower(),
        "exit_code": exit_code,
        "message": message,
        "source_hash": source_hash,
        "command": list(command or []),
        "required": bool((run.get("validation_contract") or {}).get("required")),
    }
    rows[:] = [row for row in rows if not (isinstance(row, dict) and row.get("key") == "user_validation")]
    rows.append(record)


def _find_validation_script(project_dir: Path, configured_script: str = "", fallback_scripts: list[str] | None = None) -> Path | None:
    explicit = configured_script or os.environ.get("AI_WORKFLOW_VALIDATION_SCRIPT") or os.environ.get("VALIDATION_SCRIPT")
    if explicit:
        return _resolve_explicit_script(project_dir, explicit)
    for name in fallback_scripts or []:
        candidate = (project_dir / name).resolve()
        if candidate.is_file():
            return candidate
    return None


def _fallback_validation_scripts(context: Any) -> list[str]:
    step_config = context.run.get("_current_step_config") if isinstance(getattr(context, "run", None), dict) else {}
    if not isinstance(step_config, dict):
        return []
    value = step_config.get("fallbackValidationScripts") or step_config.get("fallback_validation_scripts") or []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _requires_validation_script(context: Any) -> bool:
    if not isinstance(getattr(context, "run", None), dict):
        return False
    step_config = context.run.get("_current_step_config") or {}
    if not isinstance(step_config, dict):
        return False
    value = step_config.get("requiresValidationScript")
    if value is None:
        value = step_config.get("requires_validation_script")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _run(command: list[str], cwd: Path, *, timeout_seconds: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, timeout=max(1, timeout_seconds))


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
    source_hash: str = "",
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
            f"Source SHA-256: {source_hash or 'N/A'}",
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
