from __future__ import annotations

import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from app.runtime_modules import api as runtime
from app.core.paths import write_text
from app.services.workflow_lint_service import assert_workflow_valid, lint_workflow
from app.services import workflow_asset_service


SYSTEM_WORKFLOW_ID = "system-controlled-qwen"
SAMPLE_WORKFLOW_ID = "sample-custom-workflow"
SAMPLE_WORKFLOW_FOLDER = "sample-custom-workflow"

# Canonical workflow root. The old data/workflows bundle source is intentionally
# no longer a first-class runtime location; workflows, skill prompts, metadata,
# and Python functions all live under data/ai-workflow/.
AI_WORKFLOW_ROOT = workflow_asset_service.GLOBAL_ASSET_ROOT
WORKFLOWS_DIR = AI_WORKFLOW_ROOT / "workflows"
STEPS_DIR = AI_WORKFLOW_ROOT / "steps"
CONTRACTS_DIR = AI_WORKFLOW_ROOT / "contracts"
FUNCTIONS_DIR = AI_WORKFLOW_ROOT / "functions"
WORKFLOW_ASSET_DIRS = ("steps", "contracts", "functions", "workflows")


def _sync_asset_paths() -> None:
    """Keep this module aligned when tests or callers override the asset root."""
    global AI_WORKFLOW_ROOT, WORKFLOWS_DIR, STEPS_DIR, CONTRACTS_DIR, FUNCTIONS_DIR
    root = workflow_asset_service.GLOBAL_ASSET_ROOT
    if AI_WORKFLOW_ROOT == root:
        return
    AI_WORKFLOW_ROOT = root
    WORKFLOWS_DIR = root / "workflows"
    STEPS_DIR = root / "steps"
    CONTRACTS_DIR = root / "contracts"
    FUNCTIONS_DIR = root / "functions"

PROMPT_FILE_BY_STEP_KEY = {
    "prepare_project": "00_prepare.md",
    "reason_requirement": "00_reason_requirement.md",
    "generate_spec": "01_spec.md",
    "review_spec": "02_review_spec.md",
    "generate_todo": "03_todo.md",
    "review_todo": "04_review_todo.md",
    "reason_build": "04_reason_build.md",
    "build": "05_build.md",
    "final_review": "06_final_review.md",
    "generate_tests": "07_test.md",
    "repair_spec": "08_repair_spec.md",
    "repair_todo": "09_repair_todo.md",
}

ROOT_PROMPT_FILES = tuple(dict.fromkeys(PROMPT_FILE_BY_STEP_KEY.values()))


# ---------------------------------------------------------------------------
# Paths / naming
# ---------------------------------------------------------------------------

def ensure_workflow_dir() -> None:
    _sync_asset_paths()
    workflow_asset_service.ensure_asset_dirs()


def slugify(value: str, fallback: str = "workflow") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def _step_key(value: str, fallback: str = "step") -> str:
    return slugify(value, fallback).replace("-", "_")


def unique_folder_name(base: str, workflow_id: str | None = None) -> str:
    ensure_workflow_dir()
    base_slug = slugify(workflow_id or base)
    candidate = base_slug
    index = 2
    while workflow_file(candidate).exists() or (CONTRACTS_DIR / candidate).exists() or (STEPS_DIR / candidate).exists():
        candidate = f"{base_slug}-{index}"
        index += 1
    return candidate


def workflow_file(folder_name: str) -> Path:
    _sync_asset_paths()
    name = slugify(folder_name)
    if name.endswith(".workflow"):
        return WORKFLOWS_DIR / name
    return WORKFLOWS_DIR / f"{name}.workflow"


def workflow_dir(folder_name: str) -> Path:
    _sync_asset_paths()
    # Compatibility helper for older callers/tests.  A workflow is now one
    # .workflow file plus separated steps/contracts folders, not a bundle folder.
    return WORKFLOWS_DIR


def default_prompt_path(step: dict, workflow_id: str | None = None) -> str:
    key = _step_key(step.get("key") or step.get("name") or "step")
    filename = Path(str(step.get("templatePath") or "")).name or PROMPT_FILE_BY_STEP_KEY.get(key) or f"{key}.md"
    if not filename.endswith((".md", ".markdown", ".txt")):
        filename = f"{key}.md"
    prefix = slugify(workflow_id or step.get("workflowId") or "workflow")
    return f"steps/{prefix}/{filename}"


def safe_bundle_relative_path(value: str, default: str) -> str:
    raw = (value or default).replace("\\", "/").strip() or default
    path = Path(raw)
    parts = [part for part in path.parts if part not in {"", ".", ".."}]
    if not parts:
        parts = Path(default).parts
    if parts[0] not in WORKFLOW_ASSET_DIRS and not str(raw).startswith("prompts/"):
        # Backward-compatible UI input: a bare filename means a prompt file.
        parts = ("prompts", *parts)
    return "/".join(parts)


def bundle_path(folder_name: str, relative_path: str) -> Path:
    normalized = str(relative_path or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("steps/") or normalized.startswith("contracts/"):
        return AI_WORKFLOW_ROOT / normalized
    return AI_WORKFLOW_ROOT / "steps" / slugify(folder_name) / Path(normalized).name


def _workflow_asset_rel(workflow_id: str) -> str:
    return f"workflows/{slugify(workflow_id)}.workflow"


def _contract_rel(workflow_id: str, step_key: str) -> str:
    return f"contracts/{slugify(workflow_id)}/{_step_key(step_key)}.yaml"


def _step_rel(workflow_id: str, step: dict) -> str:
    raw = str(step.get("templatePath") or step.get("skillPath") or "").replace("\\", "/").strip()
    if raw.startswith("steps/"):
        return raw
    if raw.startswith(f"{workflow_asset_service.PROJECT_ASSET_DIR}/steps/"):
        return raw[len(workflow_asset_service.PROJECT_ASSET_DIR) + 1 :]
    key = _step_key(step.get("key") or step.get("name") or "step")
    filename = Path(raw).name or PROMPT_FILE_BY_STEP_KEY.get(key) or f"{key}.md"
    if not Path(filename).suffix:
        filename = f"{filename}.md"
    return f"steps/{slugify(workflow_id)}/{filename}"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_step_config(step: dict) -> dict:
    item = deepcopy(step or {})
    item.setdefault("id", f"step-{uuid.uuid4()}")
    item.setdefault("key", _step_key(item.get("name") or item.get("id") or "step"))
    item.setdefault("name", item.get("key") or "Step")
    item.setdefault("type", "ai")
    item.setdefault("enabled", True)
    item.setdefault("description", "")
    item.setdefault("command", "")
    item.setdefault("contractId", "")
    item.setdefault("contractPath", "")
    item.setdefault("metadataPath", "")
    item.setdefault("skillPath", "")
    item.setdefault("templatePath", item.get("skillPath") or default_prompt_path(item))
    item.setdefault("filename", item.get("outputFile") or "")
    item.setdefault("outputFile", item.get("filename") or "")
    if item.get("type") in {"ai", "review", "command", "agent", "qwen"}:
        item.setdefault("agent", item.get("provider") or "qwen")
        item.setdefault("provider", item.get("agent") or "qwen")
    else:
        item.setdefault("agent", item.get("provider") or "")
        item.setdefault("provider", item.get("agent") or "")
    item.setdefault("templateContent", "")
    item.setdefault("sources", [])
    item.setdefault("reviewMode", "current_session" if item.get("type") == "review" or "review" in str(item.get("key", "")) else "none")
    item.setdefault("reviewers", [])
    item.setdefault("confidenceThreshold", 0.75)
    item.setdefault("passKeywords", "PASS, APPROVED")
    item.setdefault("failKeywords", "FAIL, BLOCKED")
    item.setdefault("aggregatorFunction", "keyword_confidence" if item.get("type") == "review" else "")
    item.setdefault("maxRetries", 2)
    item.setdefault("failAction", "same_step")
    item.setdefault("retryFromStepKey", "")
    item.setdefault("keepSameSession", True)
    item.setdefault("injectFailureFeedback", True)
    item.setdefault("stopAfterFailures", 3)
    item.setdefault("pauseAfterStep", item.get("type") in {"gate", "manual"})
    item.setdefault("approvalRequired", item.get("type") in {"gate", "manual"})
    item.setdefault("approvalMessage", "")
    item.setdefault("timeoutEnabled", False)
    item.setdefault("timeoutMinutes", 0)
    item.setdefault("allowInteraction", True)
    item.setdefault("thinking", False)
    item.setdefault("agentOptions", {})
    item.setdefault("expectedFiles", [item["outputFile"]] if item.get("outputFile") else [])
    item.setdefault("requireProjectChanges", item.get("key") == "build")
    item.setdefault("function", item.get("validator") or "")
    return item


def normalize_workflow_steps(workflow: dict) -> dict:
    item = deepcopy(workflow or {})
    item["steps"] = [normalize_step_config(step) for step in item.get("steps", [])]
    return item


def _normalize_workflow(workflow: dict, existing_folder: str | None = None) -> dict:
    item = deepcopy(workflow or {})
    item.setdefault("id", f"workflow-{uuid.uuid4()}")
    item["id"] = slugify(str(item.get("id") or item.get("name") or "workflow"))
    item.setdefault("kind", "custom")
    item.setdefault("name", "Untitled Workflow")
    item.setdefault("description", "Custom workflow.")
    item.setdefault("active", False)
    item.setdefault("protected", False)
    item.setdefault("deletable", not bool(item.get("protected")))
    item.setdefault("skillRoot", ".ai-workflow")
    item.setdefault("promptRoot", "steps/")
    item.setdefault("steps", [])
    if item.get("id") == SYSTEM_WORKFLOW_ID:
        item["kind"] = "system"
        item["protected"] = True
        item["deletable"] = False
        item["active"] = True
    elif item.get("kind") == "system":
        item["kind"] = "custom"
        item["protected"] = False
        item["deletable"] = True
    item["folderName"] = existing_folder or item.get("folderName") or item["id"]
    item["folderName"] = slugify(item["folderName"], item["id"])
    item["workflowPath"] = _workflow_asset_rel(item["id"])
    item["updated_at"] = runtime.utc_now()
    item.setdefault("created_at", item["updated_at"])
    return normalize_workflow_steps(item)


def _contract_from_step(workflow_id: str, step: dict) -> dict[str, Any]:
    item = normalize_step_config(step)
    key = _step_key(item.get("key") or item.get("name") or "step")
    skill_rel = _step_rel(workflow_id, item)
    outputs = item.get("expectedFiles") or ([item.get("outputFile")] if item.get("outputFile") else [])
    if isinstance(outputs, str):
        outputs = [outputs]
    contract = {
        "id": item.get("contractId") or key,
        "key": key,
        "name": item.get("name") or key,
        "description": item.get("description") or "",
        "enabled": item.get("enabled", True),
        "type": item.get("type") or "ai",
        "skill": skill_rel,
        "command": item.get("command") or "",
        "agent": item.get("agent") or item.get("provider") or "qwen",
        "outputs": [str(value) for value in outputs or []],
        "function": item.get("function") or item.get("validator") or "",
        "retry": int(item.get("maxRetries") or 0),
        "failAction": item.get("failAction") or "same_step",
        "retryFromStepKey": item.get("retryFromStepKey") or "",
        "keepSameSession": bool(item.get("keepSameSession", True)),
        "injectFailureFeedback": bool(item.get("injectFailureFeedback", True)),
        "stopAfterFailures": int(item.get("stopAfterFailures") or 3),
        "allowInteraction": bool(item.get("allowInteraction", True)),
        "thinking": bool(item.get("thinking", False)),
        "approvalRequired": bool(item.get("approvalRequired", False)),
        "pauseAfterStep": bool(item.get("pauseAfterStep", False)),
        "approvalMessage": item.get("approvalMessage") or "",
        "timeoutMinutes": float(item.get("timeoutMinutes") or 0),
        "timeoutEnabled": bool(item.get("timeoutEnabled", False)),
        "reviewMode": item.get("reviewMode") or "none",
        "reviewers": item.get("reviewers") or [],
        "confidenceThreshold": float(item.get("confidenceThreshold") or 0.75),
        "passKeywords": item.get("passKeywords") or "PASS, APPROVED",
        "failKeywords": item.get("failKeywords") or "FAIL, BLOCKED",
        "aggregatorFunction": item.get("aggregatorFunction") or "",
        "sources": item.get("sources") or [],
        "agentOptions": item.get("agentOptions") or {},
        "path": _contract_rel(workflow_id, key),
    }
    if contract["timeoutEnabled"] and contract["timeoutMinutes"]:
        contract["timeout"] = float(contract["timeoutMinutes"]) * 60
    return workflow_asset_service.normalize_contract(contract, fallback_id=key)


def _workflow_manifest(workflow: dict, contract_refs: list[str]) -> dict[str, Any]:
    return {
        "id": workflow["id"],
        "name": workflow.get("name") or workflow["id"],
        "description": workflow.get("description") or "",
        "kind": workflow.get("kind") or "custom",
        "active": bool(workflow.get("active", False)),
        "protected": bool(workflow.get("protected", False)),
        "deletable": bool(workflow.get("deletable", not workflow.get("protected", False))),
        "skillRoot": workflow.get("skillRoot") or ".ai-workflow",
        "promptRoot": "steps/",
        "created_at": workflow.get("created_at"),
        "updated_at": workflow.get("updated_at"),
        "steps": [{"contract": ref} for ref in contract_refs],
    }


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Persistence: workflow = .workflow manifest + contracts + step markdown
# ---------------------------------------------------------------------------

def write_workflow_assets(workflow: dict) -> dict:
    ensure_workflow_dir()
    item = _normalize_workflow(workflow, workflow.get("folderName") or workflow.get("id"))
    workflow_id = item["id"]
    (STEPS_DIR / workflow_id).mkdir(parents=True, exist_ok=True)
    (CONTRACTS_DIR / workflow_id).mkdir(parents=True, exist_ok=True)
    assert_workflow_valid(item)

    contract_refs: list[str] = []
    for step in item.get("steps", []):
        key = _step_key(step.get("key") or step.get("name") or "step")
        skill_rel = _step_rel(workflow_id, step)
        step["templatePath"] = skill_rel
        step["skillPath"] = skill_rel
        step["contractPath"] = _contract_rel(workflow_id, key)
        step["metadataPath"] = step["contractPath"]
        step["contractId"] = step.get("contractId") or key

        content = step.get("templateContent")
        if not isinstance(content, str) or not content.strip():
            existing = workflow_asset_service.resolve_asset_path(skill_rel, must_exist=False, scope="global")
            if existing.exists():
                content = existing.read_text(encoding="utf-8-sig")
            else:
                content = ""
        workflow_asset_service.write_asset(skill_rel, content or "", scope="global", overwrite=True)

        contract = _contract_from_step(workflow_id, step)
        contract_refs.append(contract["path"])
        workflow_asset_service.write_asset(contract["path"], _dump_yaml(contract), scope="global", overwrite=True)

    manifest = _workflow_manifest(item, contract_refs)
    workflow_asset_service.write_asset(_workflow_asset_rel(workflow_id), _dump_yaml(manifest), scope="global", overwrite=True)
    return read_prompt_files(workflow_asset_service.load_workflow_asset(workflow_id), item["folderName"])


def write_prompt_files(workflow: dict) -> dict:
    return write_workflow_assets(workflow)


def read_prompt_files(workflow: dict, folder_name: str | None = None) -> dict:
    item = deepcopy(workflow)
    project_path = item.get("projectPath") or item.get("project_path")
    for step in item.get("steps", []):
        raw_template_path = str(step.get("templatePath") or step.get("skillPath") or "")
        normalized = raw_template_path.replace("\\", "/")
        if normalized.startswith(f"{workflow_asset_service.PROJECT_ASSET_DIR}/"):
            normalized = normalized[len(workflow_asset_service.PROJECT_ASSET_DIR) + 1 :]
        if normalized.startswith("steps/"):
            step["templatePath"] = normalized
            step["skillPath"] = normalized
            try:
                path = workflow_asset_service.resolve_asset_path(normalized, project_path)
                step["templateContent"] = path.read_text(encoding="utf-8-sig")
            except Exception:
                step.setdefault("templateContent", "")
        else:
            # Legacy safety net: support old prompts/foo.md references by mapping
            # them into this workflow's canonical steps/<workflow-id>/ folder.
            legacy_rel = default_prompt_path(step, item.get("id") or folder_name)
            step["templatePath"] = legacy_rel
            step["skillPath"] = legacy_rel
            try:
                path = workflow_asset_service.resolve_asset_path(legacy_rel, project_path)
                step["templateContent"] = path.read_text(encoding="utf-8-sig")
            except Exception:
                step.setdefault("templateContent", "")
    return item


def read_workflow_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return workflow_asset_service.load_workflow_asset(f"workflows/{path.name}" if path.suffix == ".workflow" else path.stem)
    except Exception:
        return None


def write_workflow_file(workflow: dict) -> None:
    write_workflow_assets(workflow)


def list_workflow_files() -> list[Path]:
    ensure_workflow_dir()
    return sorted(WORKFLOWS_DIR.glob("*.workflow"))


def list_custom_workflow_files() -> list[Path]:
    paths: list[Path] = []
    for path in list_workflow_files():
        try:
            workflow = workflow_asset_service.load_workflow_asset(path.stem)
        except Exception:
            paths.append(path)
            continue
        if workflow.get("id") == SYSTEM_WORKFLOW_ID or workflow.get("kind") == "system":
            continue
        paths.append(path)
    return paths


def find_workflow_path(workflow_id: str) -> Path | None:
    target = slugify(workflow_id)
    candidate = workflow_file(target)
    if candidate.exists():
        return candidate
    for path in list_workflow_files():
        try:
            workflow = workflow_asset_service.load_workflow_asset(path.stem)
        except Exception:
            continue
        if workflow.get("id") == workflow_id:
            return path
    return None


# ---------------------------------------------------------------------------
# Built-ins and sample
# ---------------------------------------------------------------------------

def _write_minimal_system_workflow() -> None:
    now = runtime.utc_now()
    workflow = {
        "id": SYSTEM_WORKFLOW_ID,
        "kind": "system",
        "name": "Controlled Qwen Workflow",
        "description": "Default controlled workflow stored in canonical data/ai-workflow assets.",
        "active": True,
        "protected": True,
        "deletable": False,
        "folderName": SYSTEM_WORKFLOW_ID,
        "created_at": now,
        "updated_at": now,
        "steps": [
            {
                "id": "system-generate_spec",
                "key": "generate_spec",
                "name": "Generate Spec",
                "type": "ai",
                "templatePath": f"steps/{SYSTEM_WORKFLOW_ID}/01_spec.md",
                "templateContent": "Create a concise spec for:\n\n{{requirement}}\n",
                "outputFile": "spec.md",
                "expectedFiles": ["spec.md"],
                "maxRetries": 2,
                "allowInteraction": True,
            }
        ],
    }
    write_workflow_assets(workflow)


def system_workflow_with_folder() -> dict:
    ensure_workflow_dir()
    try:
        workflow = workflow_asset_service.load_workflow_asset(SYSTEM_WORKFLOW_ID)
    except HTTPException:
        _write_minimal_system_workflow()
        workflow = workflow_asset_service.load_workflow_asset(SYSTEM_WORKFLOW_ID)
    workflow["id"] = SYSTEM_WORKFLOW_ID
    workflow["kind"] = "system"
    workflow["protected"] = True
    workflow["deletable"] = False
    workflow["active"] = True
    workflow["folderName"] = SYSTEM_WORKFLOW_ID
    workflow.setdefault("skillRoot", ".ai-workflow")
    workflow.setdefault("promptRoot", "steps/")
    return read_prompt_files(normalize_workflow_steps(workflow), SYSTEM_WORKFLOW_ID)


def stored_system_workflow_config() -> dict:
    workflow = system_workflow_with_folder()
    for step in workflow.get("steps", []):
        step["templateContent"] = ""
    return workflow


def ensure_system_workflow() -> None:
    system_workflow_with_folder()


def sample_workflow_config() -> dict:
    workflow = deepcopy(stored_system_workflow_config())
    now = runtime.utc_now()
    workflow.update(
        {
            "id": SAMPLE_WORKFLOW_ID,
            "kind": "custom",
            "name": "Sample Custom Workflow",
            "description": "Editable example copied from the system workflow. Use it to learn separated steps, contracts, Python functions, review, retry, and gates.",
            "active": False,
            "protected": False,
            "deletable": True,
            "folderName": SAMPLE_WORKFLOW_FOLDER,
            "created_at": now,
            "updated_at": now,
        }
    )
    for step in workflow.get("steps", []):
        if str(step.get("id", "")).startswith("system-"):
            step["id"] = f"sample-{step['key']}"
        step["contractId"] = step.get("key") or step.get("contractId") or "step"
    return workflow


def ensure_sample_workflow() -> None:
    ensure_workflow_dir()
    if list_custom_workflow_files():
        return
    write_workflow_assets(sample_workflow_config())


# ---------------------------------------------------------------------------
# API service surface
# ---------------------------------------------------------------------------

async def list_workflows(project_path: str | None = None) -> dict:
    ensure_sample_workflow()
    custom: list[dict[str, Any]] = []
    for path in list_custom_workflow_files():
        try:
            workflow = workflow_asset_service.load_workflow_asset(path.stem, project_path=project_path)
            workflow = read_prompt_files(normalize_workflow_steps(workflow), workflow.get("folderName") or workflow.get("id"))
            custom.append(workflow)
        except Exception as exc:
            custom.append({"id": path.stem, "kind": "asset", "name": path.stem, "workflowPath": f"workflows/{path.name}", "error": str(exc), "steps": []})

    # Project-local .ai-workflow/workflows/*.workflow can override global files.
    if project_path:
        global_ids = {item.get("id") for item in custom}
        for workflow in workflow_asset_service.list_workflow_assets(project_path):
            if workflow.get("scope") != "project" or workflow.get("id") in global_ids:
                continue
            custom.append(read_prompt_files(normalize_workflow_steps(workflow), workflow.get("folderName") or workflow.get("id")))

    custom.sort(key=lambda item: (item.get("kind") == "asset", item.get("updated_at") or item.get("name") or ""), reverse=True)
    return {"system": system_workflow_with_folder(), "custom": custom, "functions": workflow_asset_service.function_catalog(project_path)}


async def get_workflow(workflow_id: str, project_path: str | None = None) -> dict:
    if workflow_id == SYSTEM_WORKFLOW_ID:
        return system_workflow_with_folder()
    try:
        workflow = workflow_asset_service.load_workflow_asset(workflow_id, project_path=project_path)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return read_prompt_files(normalize_workflow_steps(workflow), workflow.get("folderName") or workflow.get("id"))


async def upsert_workflow(workflow: dict) -> dict:
    if workflow.get("id") == SYSTEM_WORKFLOW_ID:
        raise HTTPException(status_code=400, detail="System workflow is read-only")
    existing_path = find_workflow_path(workflow.get("id", ""))
    existing = read_workflow_file(existing_path) if existing_path else None
    item = _normalize_workflow(workflow, workflow.get("folderName") or workflow.get("id"))
    if existing:
        item["created_at"] = existing.get("created_at", item["created_at"])
    return write_workflow_assets(item)


async def delete_workflow(workflow_id: str) -> dict:
    if workflow_id == SYSTEM_WORKFLOW_ID:
        raise HTTPException(status_code=400, detail="System workflow cannot be deleted")
    path = find_workflow_path(workflow_id)
    if not path:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        workflow = workflow_asset_service.load_workflow_asset(workflow_id)
    except Exception:
        workflow = {"id": workflow_id}
    if workflow.get("protected") or workflow.get("kind") == "system":
        raise HTTPException(status_code=400, detail="Protected workflow cannot be deleted")
    path.unlink(missing_ok=True)
    # Remove only folders dedicated to this workflow id. Shared/manual assets stay.
    for root in (CONTRACTS_DIR / slugify(workflow_id), STEPS_DIR / slugify(workflow_id)):
        if root.exists() and root.is_dir():
            shutil.rmtree(root)
    return {"ok": True}


async def get_functions() -> dict:
    return workflow_asset_service.function_catalog()


async def lint_workflow_config(workflow: dict) -> dict:
    item = _normalize_workflow(workflow, workflow.get("folderName") or workflow.get("id"))
    issues = lint_workflow(item)
    return {"ok": not issues, "issues": issues}
