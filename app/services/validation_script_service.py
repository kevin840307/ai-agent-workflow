from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.runtime_modules import api as runtime


def generate_validation_script(requirement: str, expected_result: str | None = None, *, project_type: str = "python") -> str:
    req = (requirement or "").strip()
    exp = (expected_result or "").strip()
    lowered = f"{req}\n{exp}".lower()
    if not req:
        raise HTTPException(status_code=400, detail="requirement is required")

    expected_files: list[str] = []
    for match in re.finditer(r"([A-Za-z0-9_./-]+\.py)", f"{req}\n{exp}"):
        expected_files.append(match.group(1).replace("\\", "/"))
    expected_files = list(dict.fromkeys(expected_files))
    if not expected_files and "sort" in lowered or "排序" in lowered:
        expected_files = ["sorting_algorithms.py"]
    if not expected_files:
        expected_files = ["workflow_mock_feature.py"]

    functions = []
    function_markers = {
        "bubble_sort": ["bubble", "氣泡"],
        "selection_sort": ["selection", "選擇"],
        "insertion_sort": ["insertion", "插入"],
        "quick_sort": ["quick", "快速"],
        "merge_sort": ["merge", "合併"],
        "heap_sort": ["heap", "堆積"],
        "shell_sort": ["shell", "希爾"],
    }
    for name, markers in function_markers.items():
        if any(marker in lowered for marker in markers):
            functions.append(name)

    lines = [
        "from pathlib import Path",
        "import importlib.util",
        "import sys",
        "",
        "PROJECT = Path.cwd()",
        f"EXPECTED_FILES = {expected_files!r}",
        f"EXPECTED_FUNCTIONS = {functions!r}",
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
        "if EXPECTED_FUNCTIONS:",
        "    module = load_module(PROJECT / EXPECTED_FILES[0])",
        "    sample = [5, 1, 3, 1, -2]",
        "    expected = sorted(sample)",
        "    for name in EXPECTED_FUNCTIONS:",
        "        assert hasattr(module, name), f'expected function missing: {name}'",
        "        result = getattr(module, name)(list(sample))",
        "        assert result == expected, f'{name} returned {result}, expected {expected}'",
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
