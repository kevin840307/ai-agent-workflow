from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

from app.runtime_modules import api as runtime


def _normalize_relative_paths(values: Iterable[str] | None, *, field: str) -> list[str]:
    normalized: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip().replace("\\", "/")
        if not value:
            continue
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise HTTPException(status_code=400, detail=f"{field} entries must stay inside the project: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _normalize_symbols(values: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if not value.isidentifier():
            raise HTTPException(status_code=400, detail=f"expectedSymbols entries must be Python identifiers: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def generate_validation_script(
    requirement: str,
    expected_result: str | None = None,
    *,
    project_type: str = "python",
    expected_files: Iterable[str] | None = None,
    expected_symbols: Iterable[str] | None = None,
) -> str:
    """Build a validator from explicit contracts only.

    ``requirement`` and ``expected_result`` are retained as human-readable API
    metadata, but are deliberately not parsed to infer filenames, symbols, task
    intent, or expected behavior. Free-form text semantic routing belongs to the
    selected agent/workflow contract, never controller keyword tables.
    """
    if not str(requirement or "").strip():
        raise HTTPException(status_code=400, detail="requirement is required")
    if str(project_type or "python").strip().lower() != "python":
        raise HTTPException(status_code=400, detail="Only explicit Python validation contracts are currently supported")

    files = _normalize_relative_paths(expected_files, field="expectedFiles")
    symbols = _normalize_symbols(expected_symbols)
    if not files:
        raise HTTPException(
            status_code=400,
            detail="expectedFiles is required; filenames are never inferred from requirement text",
        )
    if symbols and len(files) != 1:
        raise HTTPException(
            status_code=400,
            detail="expectedSymbols requires exactly one expectedFiles entry so the module is unambiguous",
        )

    lines = [
        "from pathlib import Path",
        "import importlib.util",
        "import sys",
        "",
        "PROJECT = Path.cwd()",
        f"EXPECTED_FILES = {files!r}",
        f"EXPECTED_SYMBOLS = {symbols!r}",
        "",
        "def load_module(path: Path):",
        "    spec = importlib.util.spec_from_file_location(path.stem, path)",
        "    assert spec and spec.loader, f'cannot load module: {path}'",
        "    module = importlib.util.module_from_spec(spec)",
        "    sys.modules[path.stem] = module",
        "    spec.loader.exec_module(module)",
        "    return module",
        "",
        "for rel in EXPECTED_FILES:",
        "    path = PROJECT / rel",
        "    assert path.exists(), f'expected file missing: {rel}'",
        "",
        "if EXPECTED_SYMBOLS:",
        "    module = load_module(PROJECT / EXPECTED_FILES[0])",
        "    for name in EXPECTED_SYMBOLS:",
        "        assert hasattr(module, name), f'expected symbol missing: {name}'",
        "",
        "print('validation ok')",
    ]
    return "\n".join(lines) + "\n"


def write_validation_script(project_path: str, script: str, filename: str = "validation.py") -> dict[str, Any]:
    project = runtime.resolve_project_path(project_path)
    rel = filename.strip().replace("\\", "/") or "validation.py"
    if rel.startswith("/") or ".." in Path(rel).parts:
        raise HTTPException(status_code=400, detail="validation script filename must stay inside project")
    target = project / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(script, encoding="utf-8")
    return {"path": rel, "absolute_path": str(target), "size": target.stat().st_size}
