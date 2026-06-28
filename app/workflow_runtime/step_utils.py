from __future__ import annotations

from pathlib import Path
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def format_exception(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return f"{type(exc).__name__}: {exc!r}"


def step_config(step_record: dict[str, Any] | None) -> dict[str, Any]:
    config = (step_record or {}).get("config") or {}
    return config if isinstance(config, dict) else {}


def step_prompt_name(step_record: dict[str, Any], default: str) -> str:
    config = step_config(step_record)
    value = config.get("templatePath") or config.get("promptPath") or config.get("template") or default
    return str(value or default)


def step_artifact_name(step_record: dict[str, Any], default: str) -> str:
    config = step_config(step_record)
    value = config.get("outputFile") or config.get("filename") or config.get("artifact") or default
    return normalize_artifact_name(str(value or default))


def normalize_artifact_name(value: str) -> str:
    raw = (value or "").strip().replace("\\", "/")
    if raw.startswith("output/"):
        raw = raw[len("output/") :]
    if raw.startswith("./output/"):
        raw = raw[len("./output/") :]
    return raw.lstrip("/") or "result.md"


def step_validator_name(step_record: dict[str, Any]) -> str:
    config = step_config(step_record)
    validator = config.get("validator")
    if isinstance(validator, dict):
        return str(validator.get("id") or "")
    return str(validator or "")


def step_agent_name(step_record: dict[str, Any], default: str = "") -> str:
    config = step_config(step_record)
    return str(step_record.get("agent") or config.get("agent") or config.get("provider") or default or "")


def step_review_mode(step_record: dict[str, Any]) -> str:
    config = step_config(step_record)
    return str(config.get("reviewMode") or config.get("reviewStrategy") or "none")


def bool_config(config: dict[str, Any], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
    return bool(value)


def timeout_seconds(step_record: dict[str, Any]) -> float | None:
    config = step_config(step_record)
    if not bool_config(config, "timeoutEnabled", False):
        return None
    minutes = float(config.get("timeoutMinutes") or 0)
    if minutes <= 0:
        return None
    return minutes * 60


def expected_files(step_record: dict[str, Any]) -> list[str]:
    config = step_config(step_record)
    raw = config.get("expectedFiles") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return [str(item).strip().replace("\\", "/") for item in raw if str(item or "").strip()]


def expected_file_candidates(run: dict[str, Any], rel_path: str) -> list[Path]:
    workspace = Path(run["workspace"])
    output_dir = workspace / "output"
    project_dir = Path(run.get("project_path") or workspace)
    raw_path = rel_path.strip()
    absolute_path = Path(raw_path).expanduser()
    if absolute_path.is_absolute():
        return [absolute_path]
    normalized = raw_path.replace("\\", "/").lstrip("/")
    candidates: list[Path] = []
    if normalized.startswith("output/"):
        candidates.append(workspace / normalized)
        candidates.append(output_dir / normalized[len("output/") :])
    elif normalized.startswith("input/") or normalized.startswith("prompts/") or normalized.startswith(".workflow/"):
        candidates.append(workspace / normalized)
    else:
        candidates.append(output_dir / normalized)
        candidates.append(workspace / normalized)
        candidates.append(project_dir / normalized)
    # preserve order but remove duplicates
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique
