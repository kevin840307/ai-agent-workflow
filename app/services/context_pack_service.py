from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.paths import DATA_DIR, read_text, write_text, utc_now

CONTEXT_PACKS_DIR = DATA_DIR / "context-packs"
ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".sql"}


def _slug(value: str) -> str:
    import re
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    if not slug:
        raise HTTPException(status_code=400, detail="Context pack id/name is required")
    if slug in {".", ".."} or ".." in slug:
        raise HTTPException(status_code=400, detail="Invalid context pack id")
    return slug


def ensure_context_pack_dirs() -> None:
    CONTEXT_PACKS_DIR.mkdir(parents=True, exist_ok=True)


def pack_dir(pack_id: str) -> Path:
    ensure_context_pack_dirs()
    return CONTEXT_PACKS_DIR / _slug(pack_id)


def list_context_packs() -> dict[str, Any]:
    ensure_context_pack_dirs()
    packs = []
    for root in sorted(CONTEXT_PACKS_DIR.iterdir() if CONTEXT_PACKS_DIR.exists() else []):
        if not root.is_dir():
            continue
        manifest = {}
        if (root / "context-pack.json").exists():
            try:
                manifest = json.loads(read_text(root / "context-pack.json") or "{}")
            except json.JSONDecodeError:
                manifest = {}
        files = [path.relative_to(root).as_posix() for path in sorted(root.rglob("*")) if path.is_file() and path.name != "context-pack.json"]
        packs.append({"id": root.name, "name": manifest.get("name") or root.name, "description": manifest.get("description") or "", "files": files})
    return {"root": str(CONTEXT_PACKS_DIR), "packs": packs}


def get_context_pack(pack_id: str) -> dict[str, Any]:
    root = pack_dir(pack_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Context pack not found")
    manifest_path = root / "context-pack.json"
    manifest = json.loads(read_text(manifest_path) or "{}") if manifest_path.exists() else {"id": root.name, "name": root.name}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "context-pack.json":
            continue
        files.append({"path": path.relative_to(root).as_posix(), "content": read_text(path)})
    return {"id": root.name, "manifest": manifest, "files": files, "prompt_context": render_context_pack_prompt(root.name)}


def save_context_pack(body: dict[str, Any]) -> dict[str, Any]:
    pack_id = _slug(str(body.get("id") or body.get("name") or ""))
    root = pack_dir(pack_id)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": pack_id,
        "name": body.get("name") or pack_id,
        "description": body.get("description") or "",
        "updated_at": utc_now(),
    }
    write_text(root / "context-pack.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    for item in body.get("files") or []:
        rel = str(item.get("path") or "").replace("\\", "/").strip()
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise HTTPException(status_code=400, detail=f"Invalid context file path: {rel}")
        if Path(rel).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"Unsupported context file type: {rel}")
        write_text(root / rel, str(item.get("content") or ""))
    return get_context_pack(pack_id)


def render_context_pack_prompt(pack_id: str | None) -> str:
    if not pack_id:
        return ""
    root = pack_dir(pack_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Context pack not found")
    chunks = [f"# Context Pack: {root.name}\n"]
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "context-pack.json" or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        chunks.append(f"\n## {rel}\n\n{read_text(path)[:40_000]}\n")
    return "\n".join(chunks).strip() + "\n"


__all__ = ["list_context_packs", "get_context_pack", "save_context_pack", "render_context_pack_prompt", "ensure_context_pack_dirs"]
