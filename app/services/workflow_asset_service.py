from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import ast
import inspect
import io
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from app.core.paths import DATA_DIR, ROOT, read_text, write_text
from app.security.workspace_guard import guarded_write_text, ensure_http_within_project, is_within
from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.step_utils import parse_function_refs


GLOBAL_ASSET_ROOT = DATA_DIR / "ai-workflow"
PROJECT_ASSET_DIR = ".ai-workflow"
ASSET_DIRS = {
    "steps": {".md", ".markdown", ".txt"},
    "contracts": {".yaml", ".yml", ".json"},
    "functions": {".py"},
    "workflows": {".workflow"},
}


def ensure_asset_dirs(project_path: str | None = None) -> None:
    for name in ASSET_DIRS:
        (GLOBAL_ASSET_ROOT / name).mkdir(parents=True, exist_ok=True)
    (GLOBAL_ASSET_ROOT / "steps" / "common").mkdir(parents=True, exist_ok=True)
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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}


def _first_present(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _set_if_present(target: dict[str, Any], source: dict[str, Any], target_key: str, *source_keys: str, transform=None) -> None:
    marker = object()
    value = _first_present(source, *(source_keys or (target_key,)), default=marker)
    if value is marker:
        return
    target[target_key] = transform(value) if transform else value


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
    workflows = []
    for item in items:
        if item["type"] != "workflows":
            continue
        try:
            workflows.append(load_workflow_asset(item["path"], project_path, scope=item["scope"]))
        except Exception as exc:
            workflows.append({"scope": item["scope"], "path": item["path"], "error": str(exc)})
    return {
        "root": str(GLOBAL_ASSET_ROOT),
        "projectRoot": str(project_root / PROJECT_ASSET_DIR) if project_root else "",
        "assets": items,
        "contracts": contracts,
        "functions": list_python_functions(project_path),
        "workflows": workflows,
    }



# Built-in function metadata that is not tied to Python execution, but is still
# displayed by the UI as selectable runtime functions.
REVIEW_STRATEGIES = [
    {"id": "current_session", "label": "Current Session Review", "description": "Reuse the current agent session and evaluate pass/fail keywords plus confidence threshold.", "ui": {"supportsPrompt": True, "supportsAgent": True, "tabs": ["basic", "review", "retry", "advanced"], "promptDefaults": True}},
    {"id": "new_agent", "label": "New Agent Review", "description": "Run review in a fresh agent session, then evaluate pass/fail keywords plus confidence threshold.", "ui": {"supportsPrompt": True, "supportsAgent": True, "tabs": ["basic", "review", "retry", "advanced"], "promptDefaults": True}},
    {"id": "multi_agent", "label": "Multi-Agent Review", "description": "Run one or more reviewer agents and aggregate with keyword_confidence, majority_vote, or all_must_pass.", "ui": {"supportsPrompt": True, "supportsAgent": True, "tabs": ["basic", "review", "retry", "advanced"], "promptDefaults": True}},
]

AGGREGATORS = [
    {"id": "keyword_confidence", "label": "Keyword + Confidence", "description": "Combine pass/fail keywords with a confidence threshold."},
    {"id": "majority_vote", "label": "Majority Vote", "description": "Pass when most reviewers pass."},
    {"id": "all_must_pass", "label": "All Must Pass", "description": "Pass only when every reviewer passes."},
]

PROMPT_PARAMS = [
    {"id": "requirement", "label": "Requirement", "description": "Main user input from the runner composer.", "sample": "Create a controllable agent workflow UI."},
    {"id": "project_path", "label": "Project Path", "description": "Current project folder path.", "sample": "C:\\Users\\kevin\\sort"},
    {"id": "workspace_path", "label": "Workspace Path", "description": "Workflow run workspace path.", "sample": "runs/workflow-001"},
    {"id": "validation_script", "label": "Validation Script", "description": "Optional run-specific Python validation script path.", "sample": "tools/check_config.py"},
    {"id": "project_overview", "label": "Project Overview", "description": "Auto-generated overview of project files and folders.", "sample": "Project files:\n- app/main.py"},
    {"id": "project_profile", "label": "Project Profile", "description": "Detected file extensions, test framework, source files, and test files from the selected project path.", "sample": "Dominant source extensions: .py (3)\nTest framework: pytest"},
    {"id": "project_index", "label": "Project Index", "description": "Deterministic Python-generated project index with profile, likely test commands, isolation rules, and visible files.", "sample": "# Project Index\nStatus: READY\n\n## Deterministic Profile\nDominant source extensions: .py (3)"},
    {"id": "architecture", "label": "Architecture", "description": "Content of architecture.md from the selected project path.", "sample": "# Architecture\nFastAPI backend with static frontend."},
    {"id": "spec", "label": "Spec", "description": "Content of output/spec.md.", "sample": "## Goal\nBuild the requested workflow feature."},
    {"id": "spec_review", "label": "Spec Review", "description": "Content of output/spec-review.md.", "sample": "Status: PASS"},
    {"id": "todo", "label": "Todo", "description": "Content of output/todo.md.", "sample": "## Todo List\n- TODO-001 Implement UI."},
    {"id": "todo_review", "label": "Todo Review", "description": "Content of output/todo-review.md.", "sample": "Status: PASS"},
    {"id": "test_plan", "label": "Test Plan", "description": "Content of output/test-plan.md.", "sample": "## Test Plan\n- TEST-001 Verify output."},
    {"id": "test_result", "label": "Test Result", "description": "Content of output/test-result.md.", "sample": "Status: FAIL\nAssertionError: expected file missing."},
    {"id": "external_validation_result", "label": "External Validation Result", "description": "Content of output/external-validation-result.md from a project-provided validation script.", "sample": "Status: PASS\nScript: validation.py"},
    {"id": "build_result", "label": "Build Result", "description": "Content of output/build-result.md.", "sample": "FILE: app/main.py\nCONTENT:\n..."},
    {"id": "auto_generation_result", "label": "Auto Generation Result", "description": "Content of output/auto-generation-result.md.", "sample": "Status: READY\nFILE: app/main.py\nCONTENT:\n..."},
    {"id": "python_gate_result", "label": "Python Gate Result", "description": "Content of output/python-gate-result.md.", "sample": "Status: PASS\nMode: pytest"},
    {"id": "final_review", "label": "Final Review", "description": "Content of output/final-review.md.", "sample": "Status: PASS"},
    {"id": "raw_spec", "label": "Raw Spec", "description": "Alias of output/spec.md for older templates.", "sample": "## Goal\nBuild the requested workflow feature."},
    {"id": "answers", "label": "Answers", "description": "User answers from previous workflow interaction.", "sample": "Use Python and FastAPI."},
    {"id": "guidance", "label": "Guidance", "description": "User guidance added during the workflow.", "sample": "Keep implementation minimal."},
    {"id": "last_error", "label": "Last Error", "description": "Latest validation, review, timeout, or runner error.", "sample": "Missing Acceptance Criteria section."},
    {"id": "failure_feedback", "label": "Failure Feedback", "description": "Accumulated failure feedback for retry prompts.", "sample": "Retry 1/2 from build: tests failed."},
    {"id": "step_output", "label": "Step Output", "description": "Current step output text when available.", "sample": "Step completed successfully."},
    {"id": "security_context", "label": "Security Scope", "description": "Content of output/security-context.md.", "sample": "# Security Scan Scope"},
    {"id": "security_candidates", "label": "Security Candidates", "description": "Multi-agent candidate files such as security-candidates-auth-config.md.", "sample": "## CAND-001"},
    {"id": "security_findings", "label": "Security Findings", "description": "Python-combined normalized findings from output/security-findings.md.", "sample": "## SEC-001"},
]


def _function_meta_from_file(path: Path, root: Path, scope: str) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    meta: dict[str, Any] = {}
    try:
        tree = ast.parse(read_text(path), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if "FUNCTION_META" in names:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, dict):
                        meta = value
                    break
    except Exception:
        meta = {}
    function_id = str(meta.get("id") or path.stem).strip()
    return {
        "id": function_id,
        "label": str(meta.get("label") or function_id.replace("_", " ").replace("-", " ").title()),
        "description": str(meta.get("description") or f"Python function asset: {rel}"),
        "path": rel,
        "scope": scope,
        "ui": meta.get("ui") if isinstance(meta.get("ui"), dict) else {},
    }


def list_python_functions(project_path: str | None = None) -> list[dict[str, Any]]:
    ensure_asset_dirs(project_path)
    roots: list[tuple[str, Path]] = [("global", GLOBAL_ASSET_ROOT)]
    project_root = _project_root(project_path)
    if project_root:
        roots.insert(0, ("project", project_root / PROJECT_ASSET_DIR))
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for scope, root in roots:
        functions_dir = root / "functions"
        if not functions_dir.exists():
            continue
        for path in sorted(functions_dir.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in seen_paths:
                continue
            meta = _function_meta_from_file(path, root, scope)
            if meta["id"] in seen_ids:
                continue
            seen_paths.add(rel)
            seen_ids.add(meta["id"])
            items.append(meta)
    return items


def function_catalog(project_path: str | None = None) -> dict[str, Any]:
    return {
        "functions": list_python_functions(project_path),
        "reviewStrategies": deepcopy(REVIEW_STRATEGIES),
        "aggregators": deepcopy(AGGREGATORS),
        "promptParams": deepcopy(PROMPT_PARAMS),
    }


def resolve_function_reference(function_ref: str, project_path: str | None = None) -> str | None:
    raw = str(function_ref or "").strip().replace("\\", "/")
    if not raw:
        return None
    if raw.startswith("functions/") and raw.endswith(".py"):
        return _clean_relative_path(raw)
    for item in list_python_functions(project_path):
        if raw in {str(item.get("id") or ""), str(item.get("path") or "")}:
            return str(item.get("path") or "")
    return None


def read_asset(relative_path: str, project_path: str | None = None, *, scope: str = "auto") -> dict[str, Any]:
    path = resolve_asset_path(relative_path, project_path, scope=scope)
    rel = _clean_relative_path(relative_path)
    resolved_scope = scope if scope in {"project", "global"} else ("project" if _project_root(project_path) and (Path(project_path).expanduser().resolve() / PROJECT_ASSET_DIR) in path.parents else "global")
    return {"scope": resolved_scope, "path": rel, "content": read_text(path)}


def write_asset(relative_path: str, content: str, project_path: str | None = None, *, scope: str = "global", overwrite: bool = True) -> dict[str, Any]:
    rel = _clean_relative_path(relative_path)
    _validate_content(rel, content)
    path = resolve_asset_path(rel, project_path, must_exist=False, scope=scope)
    if scope == "project":
        ensure_http_within_project(project_path, path, action="write workflow asset")
    if path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"Workflow asset already exists: {rel}")
    write_text(path, content)
    return read_asset(rel, project_path if scope == "project" else None, scope=scope)


def delete_asset(relative_path: str, project_path: str | None = None, *, scope: str = "global") -> dict[str, Any]:
    rel = _clean_relative_path(relative_path)
    path = resolve_asset_path(rel, project_path, scope=scope)
    if scope == "project":
        ensure_http_within_project(project_path, path, action="delete workflow asset")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Workflow asset not found: {rel}")
    path.unlink()
    # Keep the top-level asset folders stable, but remove empty nested folders.
    root = (Path(project_path).expanduser().resolve() / PROJECT_ASSET_DIR) if scope == "project" and project_path else GLOBAL_ASSET_ROOT
    parent = path.parent
    while parent != root and parent.parent != parent:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent
    return {"ok": True, "path": rel, "scope": scope}


def rename_asset(
    old_path: str,
    new_path: str,
    project_path: str | None = None,
    *,
    scope: str = "global",
    overwrite: bool = False,
) -> dict[str, Any]:
    old_rel = _clean_relative_path(old_path)
    new_rel = _clean_relative_path(new_path)
    if old_rel.split("/", 1)[0] != new_rel.split("/", 1)[0]:
        raise HTTPException(status_code=400, detail="Cannot move workflow assets between asset categories")
    old_file = resolve_asset_path(old_rel, project_path, scope=scope)
    new_file = resolve_asset_path(new_rel, project_path, must_exist=False, scope=scope)
    if scope == "project":
        ensure_http_within_project(project_path, old_file, action="rename workflow asset")
        ensure_http_within_project(project_path, new_file, action="rename workflow asset")
    if new_file.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"Workflow asset already exists: {new_rel}")
    content = read_text(old_file)
    _validate_content(new_rel, content)
    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.replace(new_file) if overwrite else old_file.rename(new_file)
    return read_asset(new_rel, project_path if scope == "project" else None, scope=scope)


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

    aliases = {
        "skill_path": "skillPath",
        "template_path": "templatePath",
        "metadata_path": "metadataPath",
        "contract_path": "contractPath",
        "max_retries": "maxRetries",
        "expected_files": "expectedFiles",
        "output_file": "outputFile",
        "confidence_threshold": "confidenceThreshold",
        "pass_keywords": "passKeywords",
        "fail_keywords": "failKeywords",
        "aggregator_function": "aggregatorFunction",
        "fail_action": "failAction",
        "retry_from_step_key": "retryFromStepKey",
        "keep_same_session": "keepSameSession",
        "inject_failure_feedback": "injectFailureFeedback",
        "stop_after_failures": "stopAfterFailures",
        "allow_interaction": "allowInteraction",
        "requires_validation_script": "requiresValidationScript",
        "fallback_validation_scripts": "fallbackValidationScripts",
        "approval_required": "approvalRequired",
        "pause_after_step": "pauseAfterStep",
        "approval_message": "approvalMessage",
        "timeout_minutes": "timeoutMinutes",
        "review_mode": "reviewMode",
        "session_mode": "sessionMode",
        "agent_options": "agentOptions",
    }
    for old_key, new_key in aliases.items():
        if old_key in item and new_key not in item:
            item[new_key] = item[old_key]

    if item.get("skillPath") and not item.get("skill"):
        item["skill"] = item["skillPath"]
    if item.get("templatePath") and not item.get("skill"):
        item["skill"] = item["templatePath"]
    if item.get("metadataPath") and not item.get("path"):
        item["path"] = item["metadataPath"]
    if item.get("contractPath") and not item.get("path"):
        item["path"] = item["contractPath"]
    if item.get("retry") is None and item.get("maxRetries") is not None:
        item["retry"] = item.get("maxRetries")
    if item.get("provider") and not item.get("agent"):
        item["agent"] = item["provider"]
    if item.get("engine") and not item.get("agent"):
        item["agent"] = item["engine"]
    if item.get("output") and not item.get("outputs"):
        item["outputs"] = [item["output"]]
    if item.get("outputFile") and not item.get("outputs"):
        item["outputs"] = [item["outputFile"]]
    if item.get("expectedFiles") and not item.get("outputs"):
        item["outputs"] = item["expectedFiles"]
    if item.get("timeout") is None and item.get("timeoutMinutes") is not None:
        item["timeout"] = float(item.get("timeoutMinutes") or 0) * 60
    if item.get("functionPath") and not item.get("function"):
        item["function"] = item["functionPath"]
    if item.get("pythonFunction") and not item.get("function"):
        item["function"] = item["pythonFunction"]
    if isinstance(item.get("validation"), str) and not item.get("function"):
        item["function"] = item["validation"]
    if isinstance(item.get("validation"), dict) and not item.get("function"):
        item["function"] = item["validation"].get("function") or item["validation"].get("path") or item["validation"].get("id")
    parsed_functions = parse_function_refs(item.get("functions") if item.get("functions") is not None else item.get("function"))
    if parsed_functions:
        item["functions"] = parsed_functions
        item["function"] = parsed_functions[0]
    if item.get("approval") is None and item.get("approvalRequired") is not None:
        item["approval"] = item.get("approvalRequired")
    return item

def _contract_reference_candidates(value: str, project_path: str | None = None) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Contract id/path is required")
    normalized = raw.replace("\\", "/")
    if normalized.startswith(f"{PROJECT_ASSET_DIR}/"):
        normalized = normalized[len(PROJECT_ASSET_DIR) + 1 :]
    if normalized.startswith("contracts/"):
        return [normalized]

    suffix = Path(normalized).suffix.lower()
    preferred: list[str]
    if suffix in ASSET_DIRS["contracts"]:
        if "/" in normalized:
            preferred = [f"contracts/{normalized}"]
        else:
            preferred = [f"contracts/{normalized}"]
    else:
        preferred = [f"contracts/{normalized}.yaml"]
    return _unique_strings(preferred)


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _load_contract_by_id_or_path(value: str, project_path: str | None = None) -> dict[str, Any]:
    path_value = ""
    path: Path | None = None
    raw = str(value or "").strip()
    raw_path = Path(raw).expanduser()
    if raw_path.is_absolute():
        if not raw_path.exists():
            raise HTTPException(status_code=404, detail=f"Workflow asset not found: {value}")
        path = raw_path
        path_value = raw_path.name
    else:
        for candidate in _contract_reference_candidates(value, project_path):
            try:
                path = resolve_asset_path(candidate, project_path)
                path_value = candidate
                break
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        if path is None:
            candidates = ", ".join(_contract_reference_candidates(value, project_path)[:5])
            raise HTTPException(status_code=404, detail=f"Workflow contract not found: {value}. Tried: {candidates}")
    contract = normalize_contract(_read_structured_file(path), fallback_id=Path(path_value).stem)
    contract["path"] = _clean_relative_path(path_value) if str(path_value).startswith("contracts/") else ""
    return contract


def apply_contracts_to_workflow(workflow: dict[str, Any], project_path: str | None = None) -> dict[str, Any]:
    item = deepcopy(workflow)
    steps = []
    for step in item.get("steps", []):
        next_step = deepcopy(step)
        contract_ref = next_step.get("contractPath") or next_step.get("metadataPath") or next_step.get("contractId")
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
    item["contractPath"] = metadata.get("path") or item.get("contractPath") or ""
    item["metadataPath"] = metadata.get("path") or item.get("metadataPath") or ""

    direct_fields = {
        "name": str,
        "description": str,
        "type": str,
        "command": str,
        "reviewMode": str,
        "passKeywords": str,
        "failKeywords": str,
        "aggregatorFunction": str,
        "failAction": str,
        "retryFromStepKey": str,
        "approvalMessage": str,
        "sessionMode": str,
    }
    for field, transform in direct_fields.items():
        _set_if_present(item, metadata, field, field, transform=transform)

    for field in ["enabled", "keepSameSession", "injectFailureFeedback", "allowInteraction", "requiresValidationScript", "thinking"]:
        _set_if_present(item, metadata, field, field, transform=_coerce_bool)
    for field in ["stopAfterFailures"]:
        _set_if_present(item, metadata, field, field, transform=lambda value: int(value or 0))
    _set_if_present(item, metadata, "confidenceThreshold", "confidenceThreshold", transform=lambda value: float(value or 0))

    if metadata.get("skill"):
        item["skillPath"] = metadata["skill"]
        item["templatePath"] = metadata["skill"]
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
        if outputs:
            item["outputFile"] = str(outputs[0])
            item["filename"] = str(outputs[0])
    raw_functions = metadata.get("functions") if metadata.get("functions") is not None else metadata.get("function")
    functions = parse_function_refs(raw_functions)
    if functions:
        item["functions"] = functions
        item["function"] = functions[0]
    elif metadata.get("function") is not None:
        item["functions"] = []
        item["function"] = ""
    if metadata.get("timeout") is not None:
        seconds = float(metadata.get("timeout") or 0)
        item["timeoutEnabled"] = seconds > 0
        item["timeoutMinutes"] = round(seconds / 60, 3) if seconds > 0 else 0
    if metadata.get("timeoutEnabled") is not None:
        item["timeoutEnabled"] = _coerce_bool(metadata.get("timeoutEnabled"))
    if metadata.get("timeoutMinutes") is not None:
        item["timeoutMinutes"] = float(metadata.get("timeoutMinutes") or 0)
        item["timeoutEnabled"] = item["timeoutMinutes"] > 0 or bool(item.get("timeoutEnabled"))
    approval = _first_present(metadata, "approval", "approvalRequired", "pauseAfterStep")
    if approval is not None:
        item["approvalRequired"] = _coerce_bool(approval)
        item["pauseAfterStep"] = _coerce_bool(approval)
    if metadata.get("pauseAfterStep") is not None:
        item["pauseAfterStep"] = _coerce_bool(metadata.get("pauseAfterStep"))
    if isinstance(metadata.get("reviewers"), list):
        item["reviewers"] = deepcopy(metadata["reviewers"])
    if isinstance(metadata.get("sources"), list):
        item["sources"] = deepcopy(metadata["sources"])
    if isinstance(metadata.get("agentOptions"), dict):
        item["agentOptions"] = deepcopy(metadata["agentOptions"])
    if isinstance(metadata.get("fallbackValidationScripts"), list):
        item["fallbackValidationScripts"] = [str(value) for value in metadata["fallbackValidationScripts"]]
    elif isinstance(metadata.get("fallbackValidationScripts"), str):
        item["fallbackValidationScripts"] = [
            value.strip()
            for value in metadata["fallbackValidationScripts"].split(",")
            if value.strip()
        ]
    return item



def _slug(value: str, fallback: str = "step") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def _step_key(value: str, fallback: str = "step") -> str:
    return _slug(value, fallback).replace("-", "_")


def _workflow_roots(project_path: str | None = None) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    project_root = _project_root(project_path)
    if project_root:
        roots.append(("project", project_root / PROJECT_ASSET_DIR))
    roots.append(("global", GLOBAL_ASSET_ROOT))
    return roots


def list_workflow_asset_paths(project_path: str | None = None) -> list[tuple[str, Path]]:
    ensure_asset_dirs(project_path)
    seen: set[str] = set()
    paths: list[tuple[str, Path]] = []
    for scope, root in _workflow_roots(project_path):
        workflows_dir = root / "workflows"
        if not workflows_dir.exists():
            continue
        for path in sorted(workflows_dir.glob("*.workflow")):
            if path.stem in seen:
                continue
            seen.add(path.stem)
            paths.append((scope, path))
    return paths


def _workflow_path_by_id(workflow_id: str, project_path: str | None = None) -> tuple[str, Path] | None:
    target = str(workflow_id or "").strip()
    if not target:
        return None
    if target.endswith(".workflow") or target.startswith("workflows/") or target.startswith(f"{PROJECT_ASSET_DIR}/workflows/"):
        rel = target
        if rel.startswith(f"{PROJECT_ASSET_DIR}/"):
            rel = rel[len(PROJECT_ASSET_DIR) + 1:]
        try:
            path = resolve_asset_path(rel, project_path)
        except HTTPException:
            return None
        scope = "project" if _project_root(project_path) and (_project_root(project_path) / PROJECT_ASSET_DIR) in path.parents else "global"
        return scope, path
    for scope, path in list_workflow_asset_paths(project_path):
        if path.stem == target:
            return scope, path
    return None


def _workflow_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _workflow_document(path: Path) -> dict[str, Any] | None:
    text = read_text(path)
    if not text.strip():
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _workflow_ref_from_structured_step(step: Any) -> str | dict[str, Any]:
    if isinstance(step, str):
        return step.strip()
    if not isinstance(step, dict):
        raise HTTPException(status_code=400, detail="Structured workflow steps must be strings or objects")
    for key in ("contract", "metadata", "path", "step", "skill"):
        if step.get(key):
            return str(step[key]).strip()
    # Inline metadata is supported for small ad-hoc .workflow files, although the
    # recommended maintainable format is a separate contracts/*.yaml file.
    return step


def _expand_workflow_refs(path: Path, project_path: str | None = None, seen: set[Path] | None = None) -> list[str | dict[str, Any]]:
    seen = seen or set()
    resolved = path.resolve()
    if resolved in seen:
        raise HTTPException(status_code=400, detail=f"Workflow include cycle detected: {path.name}")
    seen.add(resolved)
    refs: list[str | dict[str, Any]] = []

    document = _workflow_document(path)
    if document and isinstance(document.get("steps"), list):
        includes = document.get("workflows") or document.get("includes") or []
        if isinstance(includes, str):
            includes = [includes]
        for include in includes if isinstance(includes, list) else []:
            found = _workflow_path_by_id(str(include), project_path)
            if not found:
                raise HTTPException(status_code=404, detail=f"Included workflow not found: {include}")
            refs.extend(_expand_workflow_refs(found[1], project_path, seen))
        refs.extend(_workflow_ref_from_structured_step(step) for step in document.get("steps") or [])
        seen.remove(resolved)
        return refs

    for line in _workflow_lines(path):
        if line.startswith("workflow:"):
            include = line.split(":", 1)[1].strip()
            found = _workflow_path_by_id(include, project_path)
            if not found:
                raise HTTPException(status_code=404, detail=f"Included workflow not found: {include}")
            refs.extend(_expand_workflow_refs(found[1], project_path, seen))
        elif line.startswith("@"):
            include = line[1:].strip()
            found = _workflow_path_by_id(include, project_path)
            if not found:
                raise HTTPException(status_code=404, detail=f"Included workflow not found: {include}")
            refs.extend(_expand_workflow_refs(found[1], project_path, seen))
        elif any(line.startswith(prefix) for prefix in ("step:", "skill:", "contract:")):
            refs.append(line.split(":", 1)[1].strip())
        else:
            refs.append(line)
    seen.remove(resolved)
    return refs


def _contract_for_ref(ref: str, project_path: str | None = None) -> dict[str, Any]:
    value = str(ref or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Workflow step reference cannot be empty")
    try:
        return _load_contract_by_id_or_path(value, project_path)
    except HTTPException as exc:
        normalized = value.replace("\\", "/")
        if exc.status_code != 404 or not (normalized.startswith("steps/") or normalized.startswith(f"{PROJECT_ASSET_DIR}/steps/") or normalized.endswith((".md", ".markdown", ".txt"))):
            raise
        skill = normalized[len(PROJECT_ASSET_DIR) + 1:] if normalized.startswith(f"{PROJECT_ASSET_DIR}/") else normalized
        path = resolve_asset_path(skill if skill.startswith("steps/") else f"steps/{Path(skill).name}", project_path)
        rel = path.relative_to(_project_root(project_path) / PROJECT_ASSET_DIR).as_posix() if _project_root(project_path) and (_project_root(project_path) / PROJECT_ASSET_DIR) in path.parents else path.relative_to(GLOBAL_ASSET_ROOT).as_posix()
        return normalize_contract({"id": Path(rel).stem, "skill": rel, "type": "ai", "path": ""}, fallback_id=Path(rel).stem)


def step_from_contract(contract: dict[str, Any], index: int = 0) -> dict[str, Any]:
    metadata = normalize_contract(contract, fallback_id=f"step-{index + 1}")
    step_id = str(metadata.get("id") or f"step-{index + 1}")
    key = _step_key(step_id, f"step_{index + 1}")
    outputs = metadata.get("outputs") or []
    if isinstance(outputs, str):
        outputs = [outputs]
    output_file = str(outputs[0]) if outputs else ""
    step = {
        "id": f"asset-{key}",
        "key": key,
        "name": str(metadata.get("name") or step_id.replace("_", " ").replace("-", " ").title()),
        "description": str(metadata.get("description") or ""),
        "type": str(metadata.get("type") or "ai"),
        "enabled": bool(metadata.get("enabled", True)),
        "contractId": step_id,
        "contractPath": str(metadata.get("path") or ""),
        "metadataPath": str(metadata.get("path") or ""),
        "skillPath": str(metadata.get("skill") or ""),
        "templatePath": str(metadata.get("skill") or ""),
        "command": str(metadata.get("command") or ""),
        "agent": str(metadata.get("agent") or metadata.get("provider") or "qwen"),
        "provider": str(metadata.get("agent") or metadata.get("provider") or "qwen"),
        "filename": output_file,
        "outputFile": output_file,
        "expectedFiles": [str(item) for item in outputs],
        "functions": parse_function_refs(metadata.get("functions") if metadata.get("functions") is not None else metadata.get("function")),
        "function": (parse_function_refs(metadata.get("functions") if metadata.get("functions") is not None else metadata.get("function")) or [""])[0],
        "maxRetries": int(metadata.get("retry") or metadata.get("maxRetries") or 0),
        "timeoutEnabled": bool(metadata.get("timeout")),
        "timeoutMinutes": round(float(metadata.get("timeout") or 0) / 60, 3) if metadata.get("timeout") else 0,
        "allowInteraction": _coerce_bool(metadata.get("allowInteraction", False)),
        "requiresValidationScript": _coerce_bool(metadata.get("requiresValidationScript", False)),
        "thinking": _coerce_bool(metadata.get("thinking", False)),
        "pauseAfterStep": _coerce_bool(metadata.get("approval", False)),
        "approvalRequired": _coerce_bool(metadata.get("approval", False)),
        "sources": [],
        "reviewers": metadata.get("reviewers") if isinstance(metadata.get("reviewers"), list) else [],
        "reviewMode": str(metadata.get("reviewMode") or metadata.get("review_strategy") or ("current_session" if str(metadata.get("type") or "") == "review" else "none")),
        "confidenceThreshold": float(metadata.get("confidenceThreshold") or metadata.get("confidence_threshold") or 0.75),
        "passKeywords": str(metadata.get("passKeywords") or "PASS, APPROVED"),
        "failKeywords": str(metadata.get("failKeywords") or "FAIL, BLOCKED"),
        "aggregatorFunction": str(metadata.get("aggregatorFunction") or metadata.get("aggregator") or ""),
        "failAction": str(metadata.get("failAction") or "same_step"),
        "retryFromStepKey": str(metadata.get("retryFromStepKey") or ""),
        "keepSameSession": _coerce_bool(metadata.get("keepSameSession", True)) and str(metadata.get("sessionMode") or "") not in {"isolated", "fresh", "new"},
        "injectFailureFeedback": bool(metadata.get("injectFailureFeedback", True)),
        "stopAfterFailures": int(metadata.get("stopAfterFailures") or 3),
        "templateContent": "",
    }
    for field in (
        "artifactPattern",
        "outputPattern",
        "innerValidator",
        "candidateValidator",
        "agentCount",
        "agentMaxRetries",
        "freshSessionPerAgent",
        "forceFreshQwenSession",
        "isolatedQwenSession",
    ):
        if field in metadata:
            step[field] = metadata[field]
    return apply_contract_to_step(step, metadata)


def load_ad_hoc_workflow_asset(
    *,
    skill: str | None = None,
    config: str | None = None,
    project_path: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Build a one-step workflow from a skill/slash command plus metadata.

    This is used by lightweight CLI shapes such as
    ``/wstep steps/build.md contracts/build.yaml "..."`` without requiring the
    caller to create a dedicated .workflow file first.
    """
    skill_value = str(skill or "").strip()
    config_value = str(config or "").strip()
    if not skill_value and not config_value:
        raise HTTPException(status_code=400, detail="skill or config is required for ad-hoc workflow runs")

    if config_value:
        metadata = _load_contract_by_id_or_path(config_value, project_path)
    else:
        fallback_id = Path(skill_value.lstrip("/")).stem or "ad-hoc"
        metadata = normalize_contract({"id": fallback_id, "key": fallback_id, "type": "ai"}, fallback_id=fallback_id)

    metadata = deepcopy(metadata)
    original_path = str(metadata.get("path") or "")
    metadata["path"] = ""

    inline_template = ""
    if skill_value:
        if _is_agent_slash_command(skill_value):
            metadata["command"] = skill_value
            if not metadata.get("skill"):
                inline_template = _default_inline_skill_template(skill_value)
        else:
            metadata["skill"] = _normalize_skill_reference(skill_value, original_path)

    if not metadata.get("skill") and not inline_template:
        raise HTTPException(
            status_code=400,
            detail="Ad-hoc workflow needs a skill markdown file, a config with skill, or an agent slash command.",
        )

    step = step_from_contract(metadata, 0)
    if inline_template:
        step["templateContent"] = inline_template
        step["templatePath"] = ""
        step["skillPath"] = ""
    workflow_folder = workflow_id or _slug(str(metadata.get("id") or "ad-hoc"), "ad-hoc")
    workflow_name = str(metadata.get("name") or workflow_folder).replace("_", " ").replace("-", " ").title()
    return {
        "id": workflow_id or f"ad-hoc-{step.get('key') or 'step'}",
        "kind": "ad_hoc",
        "name": f"Ad-hoc {workflow_name}",
        "description": "Runtime workflow built from CLI/API skill and config arguments.",
        "active": False,
        "protected": False,
        "deletable": False,
        "folderName": workflow_folder,
        "skillRoot": ".ai-workflow",
        "promptRoot": "steps/",
        "workflowPath": "",
        "scope": "runtime",
        "projectPath": str(_project_root(project_path) or ""),
        "steps": [step],
    }


def _is_agent_slash_command(value: str) -> bool:
    raw = str(value or "").strip()
    return raw.startswith("/") and not Path(raw).expanduser().is_absolute()


def _normalize_skill_reference(value: str, contract_path: str, workflow_id: str | None = None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return raw
    if raw.startswith(f"{PROJECT_ASSET_DIR}/"):
        raw = raw[len(PROJECT_ASSET_DIR) + 1 :]
    if raw.startswith("steps/") or Path(raw).expanduser().is_absolute():
        return raw
    if "/" in raw:
        return f"steps/{raw}" if Path(raw).suffix.lower() in ASSET_DIRS["steps"] else raw
    suffix = Path(raw).suffix.lower()
    if suffix in ASSET_DIRS["steps"]:
        contract_parts = contract_path.replace("\\", "/").split("/")
        if len(contract_parts) >= 3 and contract_parts[0] == "contracts":
            return f"steps/{contract_parts[1]}/{raw}"
        if workflow_id:
            return f"steps/{_slug(workflow_id, workflow_id)}/{raw}"
        return f"steps/{raw}"
    return raw


def _default_inline_skill_template(command: str) -> str:
    return (
        "Use the agent slash command above for this workflow step.\n\n"
        "Requirement:\n\n{{requirement}}\n\n"
        "Project path: {{project_path}}\n\n"
        "Follow the step metadata for retry, timeout, expected files, and validation."
    )


def load_workflow_asset(workflow_id_or_path: str, project_path: str | None = None, *, scope: str = "auto") -> dict[str, Any]:
    if scope in {"global", "project"} and str(workflow_id_or_path).startswith("workflows/"):
        path = resolve_asset_path(workflow_id_or_path, project_path, scope=scope)
        resolved_scope = scope
    else:
        found = _workflow_path_by_id(workflow_id_or_path, project_path)
        if not found:
            raise HTTPException(status_code=404, detail=f"Workflow asset not found: {workflow_id_or_path}")
        resolved_scope, path = found

    document = _workflow_document(path) or {}
    refs = _expand_workflow_refs(path, project_path)
    steps = [step_from_contract(ref if isinstance(ref, dict) else _contract_for_ref(ref, project_path), index) for index, ref in enumerate(refs)]
    project_root = _project_root(project_path)
    rel_path = path.relative_to(project_root / PROJECT_ASSET_DIR).as_posix() if project_root and (project_root / PROJECT_ASSET_DIR) in path.parents else path.relative_to(GLOBAL_ASSET_ROOT).as_posix()
    workflow_id = str(document.get("id") or path.stem)
    name = str(document.get("name") or path.stem.replace("-", " ").replace("_", " ").title())
    kind = str(document.get("kind") or "asset")
    protected = _coerce_bool(document.get("protected"), False)
    return {
        "id": workflow_id,
        "kind": kind,
        "name": name,
        "description": str(document.get("description") or f"Filesystem workflow loaded from {rel_path}. Add/edit .workflow, contracts, steps, shared markdown, and Python functions without code changes."),
        "active": _coerce_bool(document.get("active"), False),
        "protected": protected,
        "deletable": _coerce_bool(document.get("deletable"), (not protected) if isinstance(document.get("steps"), list) else False),
        "folderName": str(document.get("folderName") or workflow_id),
        "skillRoot": str(document.get("skillRoot") or ".ai-workflow"),
        "promptRoot": str(document.get("promptRoot") or "steps/"),
        "workflowPath": rel_path,
        "scope": resolved_scope,
        "projectPath": str(project_root or ""),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "steps": steps,
    }

def list_workflow_assets(project_path: str | None = None) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    for scope, path in list_workflow_asset_paths(project_path):
        try:
            workflows.append(load_workflow_asset(path.stem, project_path, scope=scope))
        except Exception as exc:
            workflows.append({
                "id": path.stem,
                "kind": "asset",
                "name": path.stem,
                "scope": scope,
                "workflowPath": path.name,
                "error": str(exc),
                "steps": [],
            })
    return workflows

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
    except Exception:
        return False
    runner = getattr(module, "run", None)
    if not callable(runner):
        return False

    async def _noop_log(_run: dict[str, Any], _message: str) -> None:
        return None

    async def _noop_refresh(_run_id: str) -> None:
        return None

    project_root = Path(run.get("project_path") or ROOT).expanduser().resolve()

    workspace_root = Path(run.get("workspace") or output_dir.parent).expanduser().resolve()

    def project_scoped_write(path: Path, content: str) -> None:
        target = Path(path).expanduser().resolve()
        if is_within(workspace_root, target):
            write_text(target, content)
            return
        guarded_write_text(project_root, target, content, write_text)

    ctx = WorkflowFunctionContext(
        run=run,
        output_dir=output_dir,
        project_dir=project_root,
        root_dir=ROOT,
        read_text=read_text,
        write_text=project_scoped_write,
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
