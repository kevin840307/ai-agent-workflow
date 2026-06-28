from __future__ import annotations

import re
from pathlib import Path

from app.runtime_paths import DEFAULT_SKILL_PATH, read_text


def resolve_skill_file(skill_path: str | None) -> Path | None:
    if not skill_path:
        return None
    raw = skill_path.replace("\\", "/").strip()
    if not raw:
        return None
    if raw.startswith("~/"):
        return Path.home() / raw[2:]
    return Path(raw)


def discover_skill_files(skill_path: str | None) -> list[Path]:
    root = resolve_skill_file(skill_path)
    if not root or not root.exists():
        return []
    if root.is_file() and root.name.upper() == "SKILL.MD":
        return [root]
    files = []
    for path in root.rglob("SKILL.md"):
        if path.is_file():
            files.append(path)
    for path in root.rglob("*.md"):
        if path.is_file() and path.name.upper() != "SKILL.MD":
            files.append(path)
    return sorted(dict.fromkeys(files))


def parse_skill_meta(skill_file: Path) -> dict[str, str]:
    text = read_text(skill_file)
    name = skill_file.parent.name
    description = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = parts[1]
            for line in meta.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"')
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"')
    return {"name": name, "description": description, "path": str(skill_file)}


def load_skill_context(skill_paths: list[str] | str | None) -> tuple[str, list[Path]]:
    if isinstance(skill_paths, str):
        skill_paths = [skill_paths]
    if not skill_paths:
        return "", []
    skill_files: list[Path] = []
    for skill_path in skill_paths:
        skill_files.extend(discover_skill_files(skill_path))
    skill_files = sorted(dict.fromkeys(skill_files))[:12]
    if not skill_files:
        return f"WARNING: no configured skill files found. Checked: {', '.join(skill_paths) or DEFAULT_SKILL_PATH}", []
    chunks = []
    for skill_file in skill_files:
        chunks.append(f"<!-- Skill: {skill_file} -->\n\n{read_text(skill_file)}")
    return "\n\n---\n\n".join(chunks), skill_files


def skill_runtime_guidance(skill_files: list[Path]) -> str:
    if not skill_files:
        return ""
    names = [parse_skill_meta(path)["name"] for path in skill_files]
    lines = [
        "Selected Qwen skills were read from disk. Apply them as methodology, not as a request to call tools.",
        f"Selected skill names: {', '.join(names)}",
        "This workflow is non-interactive/headless.",
        "Never output tool-call JSON such as todo, list_directory, calculateTotal, or arbitrary name/arguments.",
        "Only output ask_user_question JSON when a missing language/stack choice for an empty project or an ambiguous core spec blocks progress.",
        "If you can proceed with reasonable assumptions, write assumptions and Unknowns in the artifact instead.",
        "The WORKFLOW STEP PROMPT below is the highest-priority output contract.",
    ]
    return "\n".join(lines)
