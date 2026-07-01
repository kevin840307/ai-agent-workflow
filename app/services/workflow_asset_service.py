from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from app.core.paths import DATA_DIR, ROOT, read_text, write_text
from app.workflow_function_modules.base import WorkflowFunctionContext, WorkflowFunctionError


GLOBAL_ASSET_ROOT = DATA_DIR / "ai-workflow"
PROJECT_ASSET_DIR = ".ai-workflow"
ASSET_DIRS = {
    "steps": {".md", ".markdown", ".txt"},
    "contracts": {".yaml", ".yml", ".json"},
    "validators": {".py"},
    "tools": {".py"},
}


def ensure_asset_dirs(project_path: str | None = None) -> None:
    for name in ASSET_DIRS:
        (GLOBAL_ASSET_ROOT / name).mkdir(parents=True, exist_ok=True)
    if project_path:
        project_root = Path(project_path).expanduser().resolve()
        for name in ASSET_DIRS:
            (project_root / PROJECT_ASSET_DIR / name).mkdir(parents=True, exist_ok=True)


def _project_root(project_path: str | None) -> Path | None:
    if not project_path:
        return None
    return Path(project_path).expanduser().resolve()


def _clean_relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(status_code=400, detail="Asset path is required")
    if raw.startswith("~/") or Path(raw).expanduser().is_absolute():
        raise HTTPException(status_code=400, detail="Asset path must be relative to the workflow asset root")
    while raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith(f"{PROJECT_ASSET_DIR}/"):
        raw = raw[len(PROJECT_ASSET_DIR) + 1 :]
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=400, detail="Invalid workflow asset path")
    if parts[0] not in ASSET_DIRS:
        raise HTTPException(status_code=400, detail=f"Asset path must start with one of: {', '.join(sorted(ASSET_DIRS))}")
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in ASSET_DIRS[parts[0]]:
        allowed = ", ".join(sorted(ASSET_DIRS[parts[0]]))
        raise HTTPException(status_code=400, detail=f"{parts[0]} assets must use one of: {allowed}")
    return "/".join(parts)


def _asset_candidates(relative_path: str, project_path: str | None = None) -> list[Path]:
    rel = _clean_relative_path(relative_path)
    candidates: list[Path] = []
    project_root = _project_root(project_path)
    if project_root:
        candidates.append(project_root / PROJECT_ASSET_DIR / rel)
    candidates.append(GLOBAL_ASSET_ROOT / rel)
    return candidates


def resolve_asset_path(relative_path: str, project_path: str | None = None, *, must_exist: bool = True, scope: str = "auto") -> Path:
    rel = _clean_relative_path(relative_path)
    ensure_asset_dirs(project_path)
    project_root = _project_root(project_path)
    if scope == "project":
        if not project_root:
            raise HTTPException(status_code=400, detail="project_path is required for project assets")
        candidate = project_root / PROJECT_ASSET_DIR / rel
        if must_exist and not candidate.exists():
            raise HTTPException(status_code=404, detail=f"Workflow asset not found: {relative_path}")
        return candidate
    if scope == "global":
        candidate = GLOBAL_ASSET_ROOT / rel
        if must_exist and not candidate.exists():
            raise HTTPException(status_code=404, detail=f"Workflow asset not found: {relative_path}")
        return candidate
    candidates = _asset_candidates(rel, project_path)
    if must_exist:
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        raise HTTPException(status_code=404, detail=f"Workflow asset not found: {relative_path}")
    return GLOBAL_ASSET_ROOT / rel


def _read_structured_file(path: Path) -> dict[str, Any]:
    text = read_text(path)
    if path.suffix.lower() == ".json":
        data = json.loads(text or "{}")
    else:
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"Asset must contain an object: {path.name}")
    return data


def _dump_contract(contract: dict[str, Any]) -> str:
    return yaml.safe_dump(contract, sort_keys=False, allow_unicode=True)


def _validate_content(relative_path: str, content: str) -> None:
    rel = _clean_relative_path(relative_path)
    path = Path(rel)
    if path.suffix.lower() == ".py":
        compile(content, rel, "exec")
    elif path.suffix.lower() == ".json":
        json.loads(content or "{}")
    elif path.suffix.lower() in {".yaml", ".yml"}:
        yaml.safe_load(content or "{}")


def list_assets(project_path: str | None = None) -> dict[str, Any]:
    ensure_asset_dirs(project_path)
    roots: list[tuple[str, Path]] = [("global", GLOBAL_ASSET_ROOT)]
    project_root = _project_root(project_path)
    if project_root:
        roots.insert(0, ("project", project_root / PROJECT_ASSET_DIR))
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for scope, root in roots:
        if not root.exists():
            continue
        for category in ASSET_DIRS:
            for path in sorted((root / category).rglob("*")):
                if not path.is_file() or path.suffix.lower() not in ASSET_DIRS[category]:
                    continue
                rel = path.relative_to(root).as_posix()
                key = (scope, rel)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "scope": scope,
                        "type": category,
                        "path": rel,
                        "name": path.name,
                        "size": path.stat().st_size,
                        "updated_at": path.stat().st_mtime,
                    }
                )
    contracts = []
    for item in items:
        if item["type"] != "contracts":
            continue
        try:
            path = resolve_asset_path(item["path"], project_path, scope=item["scope"])
            metadata = normalize_contract(_read_structured_file(path), fallback_id=Path(item["path"]).stem)
            contracts.append({"scope": item["scope"], "path": item["path"], "contract": metadata})
        except Exception as exc:
            contracts.append({"scope": item["scope"], "path": item["path"], "error": str(exc)})
    return {"root": str(GLOBAL_ASSET_ROOT), "projectRoot": str(project_root / PROJECT_ASSET_DIR) if project_root else "", "assets": items, "contracts": contracts}


def read_asset(relative_path: str, project_path: str | None = None) -> dict[str, Any]:
    path = resolve_asset_path(relative_path, project_path)
    rel = _clean_relative_path(relative_path)
    scope = "project" if _project_root(project_path) and (Path(project_path).expanduser().resolve() / PROJECT_ASSET_DIR) in path.parents else "global"
    return {"scope": scope, "path": rel, "content": read_text(path)}


def write_asset(relative_path: str, content: str, project_path: str | None = None, *, scope: str = "global", overwrite: bool = True) -> dict[str, Any]:
    rel = _clean_relative_path(relative_path)
    _validate_content(rel, content)
    path = resolve_asset_path(rel, project_path, must_exist=False, scope=scope)
    if path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"Workflow asset already exists: {rel}")
    write_text(path, content)
    return read_asset(rel, project_path if scope == "project" else None)


def write_contract(contract: dict[str, Any], project_path: str | None = None, *, scope: str = "global") -> dict[str, Any]:
    normalized = normalize_contract(contract)
    contract_id = normalized["id"]
    path = normalized.get("path") or f"contracts/{contract_id}.yaml"
    normalized["path"] = path
    return write_asset(path, _dump_contract(normalized), project_path, scope=scope, overwrite=True)


def normalize_contract(contract: dict[str, Any], *, fallback_id: str = "contract") -> dict[str, Any]:
    item = deepcopy(contract or {})
    item.setdefault("id", fallback_id)
    item["id"] = str(item["id"]).strip() or fallback_id
    if item.get("skillPath") and not item.get("skill"):
        item["skill"] = item["skillPath"]
    if item.get("templatePath") and not item.get("skill"):
        item["skill"] = item["templatePath"]
    if item.get("retry") is None and item.get("maxRetries") is not None:
        item["retry"] = item.get("maxRetries")
    if item.get("provider") and not item.get("agent"):
        item["agent"] = item["provider"]
    if item.get("engine") and not item.get("agent"):
        item["agent"] = item["engine"]
    if item.get("output") and not item.get("outputs"):
        item["outputs"] = [item["output"]]
    if isinstance(item.get("validation"), str) and not item.get("validator"):
        item["validator"] = item["validation"]
    if isinstance(item.get("validation"), dict) and not item.get("validator"):
        item["validator"] = item["validation"].get("function") or item["validation"].get("path") or item["validation"].get("id")
    return item


def _load_contract_by_id_or_path(value: str, project_path: str | None = None) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Contract id/path is required")
    if raw.startswith("contracts/") or raw.startswith(f"{PROJECT_ASSET_DIR}/contracts/"):
        path_value = raw
    else:
        path_value = f"contracts/{raw}.yaml"
    path = resolve_asset_path(path_value, project_path)
    contract = normalize_contract(_read_structured_file(path), fallback_id=Path(path_value).stem)
    contract["path"] = _clean_relative_path(path_value)
    return contract


def apply_contracts_to_workflow(workflow: dict[str, Any], project_path: str | None = None) -> dict[str, Any]:
    item = deepcopy(workflow)
    steps = []
    for step in item.get("steps", []):
        next_step = deepcopy(step)
        contract_ref = next_step.get("contractId") or next_step.get("contractPath") or next_step.get("metadataPath")
        if contract_ref:
            contract = _load_contract_by_id_or_path(str(contract_ref), project_path)
            next_step = apply_contract_to_step(next_step, contract)
        steps.append(next_step)
    item["steps"] = steps
    return item


def apply_contract_to_step(step: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    item = deepcopy(step)
    metadata = normalize_contract(contract)
    item["contractId"] = metadata.get("id") or item.get("contractId") or ""
    item["metadataPath"] = metadata.get("path") or item.get("metadataPath") or ""
    if metadata.get("skill"):
        item["skillPath"] = metadata["skill"]
        item["templatePath"] = metadata["skill"]
    if metadata.get("type"):
        item["type"] = metadata["type"]
    if metadata.get("command") is not None:
        item["command"] = metadata.get("command") or ""
    if metadata.get("agent"):
        item["agent"] = metadata["agent"]
        item["provider"] = metadata["agent"]
    if metadata.get("retry") is not None:
        item["maxRetries"] = int(metadata.get("retry") or 0)
    if metadata.get("outputs") is not None:
        outputs = metadata.get("outputs")
        if isinstance(outputs, str):
            outputs = [outputs]
        item["expectedFiles"] = [str(value) for value in outputs or []]
        if outputs and not item.get("outputFile"):
            item["outputFile"] = str(outputs[0])
            item["filename"] = str(outputs[0])
    if metadata.get("validator"):
        item["validator"] = metadata["validator"]
    if metadata.get("timeout") is not None:
        seconds = float(metadata.get("timeout") or 0)
        item["timeoutEnabled"] = seconds > 0
        item["timeoutMinutes"] = round(seconds / 60, 3) if seconds > 0 else 0
    if metadata.get("approval") is not None:
        item["approvalRequired"] = bool(metadata.get("approval"))
        item["pauseAfterStep"] = bool(metadata.get("approval"))
    if metadata.get("sessionMode"):
        item["sessionMode"] = metadata["sessionMode"]
    if metadata.get("allowInteraction") is not None:
        item["allowInteraction"] = bool(metadata.get("allowInteraction"))
    return item


async def run_python_asset(
    run: dict[str, Any],
    function_path: str,
    output_dir: Path,
    artifact: str | None = None,
) -> None:
    project_path = str(run.get("project_path") or ROOT)
    path = resolve_asset_path(function_path, project_path)
    if path.suffix.lower() != ".py":
        raise HTTPException(status_code=400, detail=f"Workflow asset is not a Python file: {function_path}")
    if await _try_run_python_asset_api(path, run, output_dir, artifact):
        return
    _run_python_asset_cli(path, run, project_path, output_dir, artifact, function_path)


async def _try_run_python_asset_api(path: Path, run: dict[str, Any], output_dir: Path, artifact: str | None) -> bool:
    module_name = f"ai_workflow_asset_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
    except SystemExit:
        return False
    runner = getattr(module, "run", None)
    if not callable(runner):
        return False

    async def _noop_log(_run: dict[str, Any], _message: str) -> None:
        return None

    async def _noop_refresh(_run_id: str) -> None:
        return None

    ctx = WorkflowFunctionContext(
        run=run,
        output_dir=output_dir,
        project_dir=Path(run.get("project_path") or ROOT),
        root_dir=ROOT,
        read_text=read_text,
        write_text=write_text,
        log=_noop_log,
        refresh_artifacts=_noop_refresh,
    )
    try:
        signature = inspect.signature(runner)
        result = runner(ctx, artifact) if len(signature.parameters) >= 2 else runner(ctx)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, str) and result.strip():
            write_text(output_dir / f"{path.stem}-result.md", result.strip() + "\n")
        return True
    except WorkflowFunctionError:
        raise
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _run_python_asset_cli(path: Path, run: dict[str, Any], project_path: str, output_dir: Path, artifact: str | None, function_path: str) -> None:
    args = [
        sys.executable,
        str(path),
        "--workspace",
        str(Path(run["workspace"])),
        "--project",
        project_path,
        "--output",
        str(output_dir),
    ]
    if artifact:
        args.extend(["--artifact", artifact])
    completed = subprocess.run(args, cwd=project_path, text=True, capture_output=True, timeout=None)
    transcript = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part).strip()
    if transcript:
        write_text(Path(run["workspace"]) / "output" / f"{Path(path).stem}-result.md", transcript + "\n")
    if completed.returncode != 0:
        raise RuntimeError(transcript or f"Python asset failed with exit code {completed.returncode}: {function_path}")
