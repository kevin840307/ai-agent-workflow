from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class ValidationContractError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_validation_contract(
    project_dir: Path,
    script_value: str | None,
    *,
    required: bool,
    timeout_seconds: int = 300,
) -> dict[str, Any] | None:
    raw = str(script_value or "").strip()
    if not raw:
        if required:
            raise ValidationContractError("VALIDATION_FILE_NOT_FOUND: A required validation script was not configured.")
        return None
    root = Path(project_dir).expanduser().resolve()
    candidate = Path(raw).expanduser()
    script = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not script.is_file():
        raise ValidationContractError(f"VALIDATION_FILE_NOT_FOUND: Validation script does not exist: {script}")
    if script.suffix.lower() != ".py":
        raise ValidationContractError("VALIDATION_FILE_INVALID: User validation must be a Python file.")
    try:
        display = script.relative_to(root).as_posix()
    except ValueError:
        display = str(script)
    return {
        "type": "python_script",
        "source_path": str(script),
        "display_path": display,
        "sha256": _sha256(script),
        "required": bool(required),
        "execution_phase": "final",
        "timeout_seconds": max(1, int(timeout_seconds or 300)),
        "working_directory": str(root),
        "write_policy": "read_only",
    }


def verify_validation_contract(run: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    contract = run.get("validation_contract")
    if not isinstance(contract, dict) or not contract:
        raise ValidationContractError("VALIDATION_NOT_CONFIGURED: No validation contract is configured.")
    script = Path(str(contract.get("source_path") or "")).expanduser().resolve()
    if not script.is_file():
        raise ValidationContractError(f"VALIDATION_FILE_NOT_FOUND: Validation script does not exist: {script}")
    actual = _sha256(script)
    expected = str(contract.get("sha256") or "")
    if not expected or actual != expected:
        raise ValidationContractError("VALIDATION_FILE_MUTATED: The protected user validation script changed during the run.")
    return contract, script


__all__ = ["ValidationContractError", "build_validation_contract", "verify_validation_contract"]
