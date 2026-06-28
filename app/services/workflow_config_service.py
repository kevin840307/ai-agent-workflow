from __future__ import annotations

import json
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException

from app import runtime
from app.workflow_functions import AVAILABLE_WORKFLOW_FUNCTIONS


SYSTEM_WORKFLOW_ID = "system-controlled-qwen"
SAMPLE_WORKFLOW_ID = "sample-custom-workflow"
SAMPLE_WORKFLOW_FOLDER = "sample-custom-workflow"
WORKFLOWS_DIR = runtime.DATA_DIR / "workflows"
GLOBAL_MD_DIR = runtime.DATA_DIR / "global-md"
WORKFLOW_ASSET_DIRS = ("prompts", "skills", "functions")

PROMPT_FILE_BY_STEP_KEY = {
    "prepare_project": "00_prepare.md",
    "generate_spec": "01_spec.md",
    "review_spec": "02_review_spec.md",
    "generate_todo": "03_todo.md",
    "review_todo": "04_review_todo.md",
    "build": "05_build.md",
    "final_review": "06_final_review.md",
    "generate_tests": "07_test.md",
    "repair_spec": "08_repair_spec.md",
    "repair_todo": "09_repair_todo.md",
}

ROOT_PROMPT_FILES = tuple(dict.fromkeys(PROMPT_FILE_BY_STEP_KEY.values()))


def ensure_workflow_dir() -> None:
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    GLOBAL_MD_DIR.mkdir(parents=True, exist_ok=True)
    global_readme = GLOBAL_MD_DIR / "README.md"
    if not global_readme.exists():
        global_readme.write_text(
            "# Global Markdown\n\nShared markdown files that are not owned by one workflow can live here.\n",
            encoding="utf-8",
        )


def slugify(value: str, fallback: str = "workflow") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def unique_folder_name(base: str, workflow_id: str | None = None) -> str:
    ensure_workflow_dir()
    base_slug = slugify(base)
    if workflow_id:
        base_slug = slugify(workflow_id, base_slug)
    candidate = base_slug
    index = 2
    while (WORKFLOWS_DIR / candidate).exists():
        candidate = f"{base_slug}-{index}"
        index += 1
    return candidate


def workflow_file(folder_name: str) -> Path:
    return WORKFLOWS_DIR / folder_name / "workflow.json"


def workflow_dir(folder_name: str) -> Path:
    return WORKFLOWS_DIR / folder_name


def ensure_bundle_dirs(folder_name: str) -> None:
    base = workflow_dir(folder_name)
    for name in WORKFLOW_ASSET_DIRS:
        (base / name).mkdir(parents=True, exist_ok=True)


def default_prompt_path(step: dict) -> str:
    filename = PROMPT_FILE_BY_STEP_KEY.get(step.get("key") or "")
    if filename:
        return f"prompts/{filename}"
    key = slugify(step.get("key") or step.get("name") or "step")
    return f"prompts/{key}.md"


def safe_bundle_relative_path(value: str, default: str) -> str:
    raw = (value or default).replace("\\", "/").strip()
    if not raw:
        raw = default
    path = Path(raw)
    parts = [part for part in path.parts if part not in {"", ".", ".."}]
    if not parts:
        parts = Path(default).parts
    if parts[0] not in WORKFLOW_ASSET_DIRS:
        parts = ("prompts", *parts)
    return "/".join(parts)


def bundle_path(folder_name: str, relative_path: str) -> Path:
    base = workflow_dir(folder_name).resolve()
    target = (base / relative_path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid workflow bundle path")
    return target


def prompt_seed_source(filename: str, folder_name: str) -> Path | None:
    bundle_source = WORKFLOWS_DIR / SYSTEM_WORKFLOW_ID / "prompts" / filename
    if bundle_source.exists() and not (
        folder_name == SYSTEM_WORKFLOW_ID and bundle_source == (WORKFLOWS_DIR / folder_name / "prompts" / filename)
    ):
        return bundle_source
    legacy_source = runtime.ROOT / "prompts" / filename
    return legacy_source if legacy_source.exists() else None


def read_workflow_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


def write_workflow_file(workflow: dict) -> None:
    ensure_workflow_dir()
    folder_name = workflow["folderName"]
    ensure_bundle_dirs(folder_name)
    target = workflow_file(folder_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")


def list_custom_workflow_files() -> list[Path]:
    ensure_workflow_dir()
    paths: list[Path] = []
    for path in sorted(WORKFLOWS_DIR.glob("*/workflow.json")):
        if path.parent.name == SYSTEM_WORKFLOW_ID:
            continue
        workflow = read_workflow_file(path)
        if workflow and (workflow.get("id") == SYSTEM_WORKFLOW_ID or workflow.get("kind") == "system"):
            continue
        paths.append(path)
    return paths


def find_workflow_path(workflow_id: str) -> Path | None:
    for path in list_custom_workflow_files():
        workflow = read_workflow_file(path)
        if workflow and workflow.get("id") == workflow_id:
            return path
    return None




def normalize_step_config(step: dict) -> dict:
    item = deepcopy(step or {})
    item.setdefault("id", f"step-{uuid.uuid4()}")
    item.setdefault("key", slugify(item.get("name") or item.get("id") or "step").replace("-", "_"))
    item.setdefault("name", item.get("key") or "Step")
    item.setdefault("type", "ai")
    item.setdefault("enabled", True)
    item.setdefault("description", "")
    item.setdefault("command", "")
    item.setdefault("templatePath", default_prompt_path(item))
    item.setdefault("filename", item.get("outputFile") or "")
    item.setdefault("outputFile", item.get("filename") or "")
    if item.get("type") in {"ai", "review", "command", "agent"}:
        item.setdefault("agent", item.get("provider") or "qwen")
        item.setdefault("provider", item.get("agent") or "qwen")
    else:
        item.setdefault("agent", "")
        item.setdefault("provider", "")
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
    item.setdefault("expectedFiles", [item["outputFile"]] if item.get("outputFile") else [])
    item.setdefault("validator", "")
    return item


def normalize_workflow_steps(workflow: dict) -> dict:
    item = deepcopy(workflow or {})
    item["steps"] = [normalize_step_config(step) for step in item.get("steps", [])]
    return item

def _normalize_workflow(workflow: dict, existing_folder: str | None = None) -> dict:
    item = deepcopy(workflow or {})
    item.setdefault("id", f"workflow-{uuid.uuid4()}")
    item.setdefault("kind", "custom")
    item.setdefault("name", "Untitled Workflow")
    item.setdefault("description", "Custom workflow.")
    item.setdefault("active", False)
    item.setdefault("skillRoot", "~/.qwen/skills")
    item.setdefault("promptRoot", "prompts/")
    item.setdefault("steps", [])
    item["kind"] = "custom" if item.get("kind") != "system" else "custom"
    item["protected"] = False
    item["deletable"] = True
    item["folderName"] = existing_folder or item.get("folderName") or unique_folder_name(item.get("name") or item["id"], item["id"])
    item["updated_at"] = runtime.utc_now()
    item.setdefault("created_at", item["updated_at"])
    item = normalize_workflow_steps(item)
    return item


def write_prompt_files(workflow: dict) -> dict:
    item = deepcopy(workflow)
    folder_name = item["folderName"]
    ensure_bundle_dirs(folder_name)
    for step in item.get("steps", []):
        content = step.get("templateContent")
        template_path = safe_bundle_relative_path(step.get("templatePath", ""), default_prompt_path(step))
        step["templatePath"] = template_path
        if isinstance(content, str) and content.strip():
            target = bundle_path(folder_name, template_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        step["templateContent"] = ""
    return item


def read_prompt_files(workflow: dict, folder_name: str) -> dict:
    item = deepcopy(workflow)
    for step in item.get("steps", []):
        template_path = safe_bundle_relative_path(step.get("templatePath", ""), default_prompt_path(step))
        step["templatePath"] = template_path
        path = bundle_path(folder_name, template_path)
        if path.exists() and path.is_file():
            step["templateContent"] = path.read_text(encoding="utf-8-sig")
        else:
            step.setdefault("templateContent", "")
    return item


def seed_prompts_from_root(folder_name: str, workflow: dict, overwrite: bool = False) -> None:
    ensure_bundle_dirs(folder_name)
    for filename in ROOT_PROMPT_FILES:
        source = prompt_seed_source(filename, folder_name)
        if not source:
            continue
        target = bundle_path(folder_name, f"prompts/{filename}")
        if overwrite or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")
    for step in workflow.get("steps", []):
        filename = PROMPT_FILE_BY_STEP_KEY.get(step.get("key") or "")
        if not filename:
            continue
        source = prompt_seed_source(filename, folder_name)
        if not source:
            continue
        template_path = safe_bundle_relative_path(step.get("templatePath", ""), f"prompts/{filename}")
        step["templatePath"] = template_path
        target = bundle_path(folder_name, template_path)
        if overwrite or not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")


def ensure_workflow_prompt_files(folder_name: str, workflow: dict) -> dict:
    item = deepcopy(workflow)
    ensure_bundle_dirs(folder_name)
    for step in item.get("steps", []):
        template_path = safe_bundle_relative_path(step.get("templatePath", ""), default_prompt_path(step))
        step["templatePath"] = template_path
        target = bundle_path(folder_name, template_path)
        if target.exists():
            continue
        content = step.get("templateContent")
        if isinstance(content, str) and content.strip():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            continue
        filename = PROMPT_FILE_BY_STEP_KEY.get(step.get("key") or "")
        source = prompt_seed_source(filename, folder_name) if filename else None
        if source and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")
    return item


def system_workflow_with_folder() -> dict:
    ensure_bundle_dirs(SYSTEM_WORKFLOW_ID)
    target = workflow_file(SYSTEM_WORKFLOW_ID)
    existing = read_workflow_file(target)
    if not existing:
        raise HTTPException(
            status_code=500,
            detail=f"System workflow bundle is missing: {target}",
        )
    existing["folderName"] = SYSTEM_WORKFLOW_ID
    existing["kind"] = "system"
    existing["protected"] = True
    existing["deletable"] = False
    existing.setdefault("active", True)
    existing = normalize_workflow_steps(existing)
    ensure_workflow_prompt_files(SYSTEM_WORKFLOW_ID, existing)
    return read_prompt_files(existing, SYSTEM_WORKFLOW_ID)


def stored_system_workflow_config() -> dict:
    workflow = system_workflow_with_folder()
    workflow.pop("templateContent", None)
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
            "description": "Editable example copied from the system workflow. Use it to learn how steps, validators, review, retry, and gates are configured.",
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
    seed_prompts_from_root(SAMPLE_WORKFLOW_FOLDER, workflow)
    return workflow


def ensure_sample_workflow() -> None:
    ensure_workflow_dir()
    if list_custom_workflow_files():
        return
    item = write_prompt_files(sample_workflow_config())
    write_workflow_file(item)


async def list_workflows() -> dict:
    ensure_sample_workflow()
    custom = []
    for path in list_custom_workflow_files():
        workflow = read_workflow_file(path)
        if workflow:
            normalized = _normalize_workflow(workflow, path.parent.name)
            normalized = ensure_workflow_prompt_files(path.parent.name, normalized)
            custom.append(read_prompt_files(normalized, path.parent.name))
    custom.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {
        "system": system_workflow_with_folder(),
        "custom": custom,
        "functions": AVAILABLE_WORKFLOW_FUNCTIONS,
    }


async def get_workflow(workflow_id: str) -> dict:
    if workflow_id == SYSTEM_WORKFLOW_ID:
        return system_workflow_with_folder()
    path = find_workflow_path(workflow_id)
    if not path:
        raise HTTPException(status_code=404, detail="Workflow not found")
    workflow = read_workflow_file(path)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    normalized = _normalize_workflow(workflow, path.parent.name)
    normalized = ensure_workflow_prompt_files(path.parent.name, normalized)
    return read_prompt_files(normalized, path.parent.name)


async def upsert_workflow(workflow: dict) -> dict:
    if workflow.get("id") == SYSTEM_WORKFLOW_ID:
        raise HTTPException(status_code=400, detail="System workflow is read-only")
    existing_path = find_workflow_path(workflow.get("id", ""))
    existing = read_workflow_file(existing_path) if existing_path else None
    existing_folder = existing_path.parent.name if existing_path else None
    item = _normalize_workflow(workflow, existing_folder)
    if existing:
        item["created_at"] = existing.get("created_at", item["created_at"])
    item = write_prompt_files(item)
    write_workflow_file(item)
    return read_prompt_files(item, item["folderName"])


async def delete_workflow(workflow_id: str) -> dict:
    if workflow_id == SYSTEM_WORKFLOW_ID:
        raise HTTPException(status_code=400, detail="System workflow cannot be deleted")
    path = find_workflow_path(workflow_id)
    if not path:
        raise HTTPException(status_code=404, detail="Workflow not found")
    folder = path.parent.resolve()
    workflows_root = WORKFLOWS_DIR.resolve()
    if workflows_root not in folder.parents:
        raise HTTPException(status_code=400, detail="Invalid workflow folder")
    shutil.rmtree(folder)
    return {"ok": True}


async def get_functions() -> dict:
    return AVAILABLE_WORKFLOW_FUNCTIONS
