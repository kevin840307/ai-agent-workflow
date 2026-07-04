from __future__ import annotations

from pathlib import Path

from app.core.paths import DEFAULT_SKILL_PATH, read_text


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
    if root.is_file() and root.suffix.lower() == ".md":
        return [root]
    files = []
    for path in root.rglob("SKILL.md"):
        if path.is_file():
            files.append(path)
    for path in root.rglob("*.md"):
        if path.is_file() and path.name.upper() != "SKILL.MD":
            files.append(path)
    return sorted(dict.fromkeys(files))

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
