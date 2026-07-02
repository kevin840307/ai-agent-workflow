from __future__ import annotations

from pathlib import Path, PureWindowsPath
from urllib.parse import unquote
from typing import Any

from app.runtime_modules.errors import WorkflowError


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


def parse_function_refs(value: Any) -> list[str]:
    """Return an ordered list of Python function ids/paths from UI or metadata values.

    New metadata uses `functions: [...]` for sequential execution. `function:` is
    retained as a single-value shorthand. Strings may be newline- or comma-
    separated so the UI can offer a simple ordered textarea.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        value = value.get("id") or value.get("function") or value.get("path") or ""
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(parse_function_refs(item))
        return _unique_ordered(result)
    raw = str(value or "").strip()
    if not raw:
        return []
    parts = [part.strip() for chunk in raw.splitlines() for part in chunk.split(",")]
    return _unique_ordered([part for part in parts if part])


def _unique_ordered(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def step_function_names(step_record: dict[str, Any]) -> list[str]:
    config = step_config(step_record)
    values: list[str] = []
    if config.get("functions") is not None:
        values.extend(parse_function_refs(config.get("functions")))
    if config.get("function") is not None:
        values.extend(parse_function_refs(config.get("function")))
    return _unique_ordered(values)


def step_function_name(step_record: dict[str, Any]) -> str:
    names = step_function_names(step_record)
    return names[0] if names else ""



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
    raw_path = str(rel_path or "").strip().strip("`")
    decoded = unquote(raw_path).replace("\\", "/")
    windows_path = PureWindowsPath(decoded)
    if decoded.startswith("/") or Path(decoded).expanduser().is_absolute() or windows_path.is_absolute() or windows_path.drive or decoded.startswith("//"):
        raise WorkflowError(f"Unsafe expected file path outside workflow/project boundary: {rel_path}")
    normalized = decoded.lstrip("/")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not normalized or any(part.strip() == ".." for part in parts):
        raise WorkflowError(f"Unsafe expected file path outside workflow/project boundary: {rel_path}")
    if ".qwen-workflow" in parts:
        raise WorkflowError(f"Unsafe expected file path outside workflow/project boundary: {rel_path}")
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
