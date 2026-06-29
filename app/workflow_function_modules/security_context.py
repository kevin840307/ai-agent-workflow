from __future__ import annotations

import os
from pathlib import Path

from app.workflow_function_modules.base import WorkflowFunctionContext, WorkflowFunctionError


SECURITY_CONTEXT_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".cs", ".vb", ".go", ".rs", ".php", ".rb",
    ".yml", ".yaml", ".json", ".xml", ".properties", ".ini", ".toml", ".env", ".config", ".conf",
    ".sql", ".sh", ".ps1", ".bat", ".cmd", ".dockerfile",
}


SECURITY_CONTEXT_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".qwen", ".vs", ".idea", ".vscode", ".qwen-workflow",
    "node_modules", "vendor", "bower_components",
    "venv", ".venv", "env", ".envdir",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox",
    "dist", "build", "target", "bin", "obj", "out", ".next", ".nuxt", ".svelte-kit",
    "coverage", ".coverage", "htmlcov",
    ".gradle", ".mvn", ".parcel-cache", ".turbo", ".cache",
    "logs", "log", "tmp", "temp",
}


SECURITY_CONTEXT_SKIP_FILE_NAMES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".coverage", "coverage.xml",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock",
}


SECURITY_CONTEXT_SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".pyd", ".class", ".jar", ".war", ".ear",
    ".dll", ".exe", ".pdb", ".so", ".dylib", ".o", ".obj",
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".log", ".tmp", ".cache",
}


SECURITY_KEYWORDS = [
    "password", "passwd", "secret", "token", "apikey", "api_key", "private_key", "jwt",
    "eval", "exec", "subprocess", "popen", "system(", "shell=True", "Runtime.getRuntime", "ProcessBuilder",
    "pickle", "yaml.load", "deserialize", "ObjectInputStream", "BinaryFormatter",
    "SELECT", "INSERT", "UPDATE", "DELETE", "execute(", "rawQuery", "createQuery", "SqlCommand",
    "open(", "readFile", "writeFile", "File(", "Path(", "send_file", "download", "upload",
    "http://", "requests.", "fetch(", "axios", "HttpClient", "RestTemplate", "WebClient",
    "cors", "csrf", "auth", "authorize", "permission", "role", "login", "session",
    "debug", "ssl", "verify=False", "trustAll", "AllowAnyOrigin",
]

def _is_under_security_excluded_path(relative: Path) -> bool:
    return any(part in SECURITY_CONTEXT_SKIP_DIRS for part in relative.parts[:-1])


def _safe_read_limited(path: Path, max_bytes: int) -> tuple[str, bool]:
    data = path.read_bytes()[: max_bytes + 1]
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    try:
        return data.decode("utf-8"), truncated
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), truncated


def _line_matches_security_keyword(line: str) -> bool:
    lowered = line.lower()
    return any(keyword.lower() in lowered for keyword in SECURITY_KEYWORDS)


def _security_excerpt_for_file(path: Path, project_dir: Path, max_chars: int) -> str:
    text, truncated = _safe_read_limited(path, max_chars)
    lines = text.splitlines()
    matched_indexes = [index for index, line in enumerate(lines) if _line_matches_security_keyword(line)]
    if not matched_indexes:
        matched_indexes = list(range(min(len(lines), 20)))
    selected: list[int] = []
    for index in matched_indexes[:12]:
        selected.extend(range(max(0, index - 2), min(len(lines), index + 3)))
    if not selected:
        return ""
    unique_indexes = sorted(set(selected))
    rel = path.relative_to(project_dir).as_posix()
    output = [f"### {rel}", "```text"]
    for index in unique_indexes:
        line = lines[index].rstrip()
        if len(line) > 240:
            line = line[:237] + "..."
        output.append(f"{index + 1}: {line}")
    if truncated:
        output.append("[File read truncated]")
    output.append("```")
    return "\n".join(output)


def collect_security_context(ctx: WorkflowFunctionContext) -> None:
    """Write bounded security scan context with inventory and relevant excerpts."""
    project_dir = ctx.project_dir
    if not project_dir.exists() or not project_dir.is_dir():
        raise WorkflowFunctionError(f"Project path does not exist or is not a directory: {project_dir}")

    max_inventory = int(os.environ.get("SECURITY_SCOPE_MAX_FILES", "300"))
    included_count = 0
    excluded_dir_count = 0
    excluded_file_count = 0
    inventory: list[str] = []
    excerpt_candidates: list[tuple[int, str, Path]] = []
    extension_counts: dict[str, int] = {}
    max_excerpt_files = int(os.environ.get("SECURITY_SCOPE_MAX_EXCERPT_FILES", "40"))
    max_file_bytes = int(os.environ.get("SECURITY_SCOPE_MAX_FILE_BYTES", "24000"))
    max_total_excerpt_chars = int(os.environ.get("SECURITY_SCOPE_MAX_EXCERPT_CHARS", "60000"))

    for path in sorted(project_dir.rglob("*")):
        try:
            relative = path.relative_to(project_dir)
        except ValueError:
            continue
        if path.is_dir():
            if relative.name in SECURITY_CONTEXT_SKIP_DIRS or _is_under_security_excluded_path(relative / "dummy"):
                excluded_dir_count += 1
            continue
        if not path.is_file():
            continue
        if _is_under_security_excluded_path(relative):
            excluded_file_count += 1
            continue
        if path.name.lower() in SECURITY_CONTEXT_SKIP_FILE_NAMES or path.suffix.lower() in SECURITY_CONTEXT_SKIP_SUFFIXES:
            excluded_file_count += 1
            continue
        included_count += 1
        suffix = path.suffix.lower() or "[no extension]"
        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1
        if len(inventory) < max_inventory:
            inventory.append(relative.as_posix())
        score = 0
        rel_text = relative.as_posix().lower()
        if any(keyword.lower() in rel_text for keyword in SECURITY_KEYWORDS):
            score += 3
        try:
            sample, _truncated = _safe_read_limited(path, min(max_file_bytes, 12000))
            score += sum(1 for line in sample.splitlines() if _line_matches_security_keyword(line))
        except OSError:
            sample = ""
        if score > 0:
            excerpt_candidates.append((score, relative.as_posix(), path))

    extension_summary = sorted(extension_counts.items(), key=lambda item: (-item[1], item[0]))[:30]
    excerpt_candidates.sort(key=lambda item: (-item[0], item[1]))
    excerpt_blocks: list[str] = []
    excerpt_chars = 0
    for _score, _relative, path in excerpt_candidates[:max_excerpt_files]:
        try:
            block = _security_excerpt_for_file(path, project_dir, max_file_bytes)
        except OSError:
            continue
        if not block.strip():
            continue
        if excerpt_chars + len(block) > max_total_excerpt_chars:
            break
        excerpt_blocks.append(block)
        excerpt_chars += len(block)

    sections: list[str] = [
        "Status: DONE",
        "",
        "# Security Scan Scope",
        "",
        f"Project path: {project_dir}",
        "Source content embedded: Bounded security-relevant excerpts",
        "Agent input mode: Use Project Path plus the bounded excerpts below. If direct file tools are unavailable, base candidates only on these excerpts and state limitations.",
        f"Included file count: {included_count}",
        f"Excluded directory count: {excluded_dir_count}",
        f"Excluded file count: {excluded_file_count}",
        f"Excerpt file count: {len(excerpt_blocks)}",
        "",
        "## Exclusion Rules",
        "- Excluded directories: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_DIRS)),
        "- Excluded file names: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_FILE_NAMES)),
        "- Excluded suffixes: " + ", ".join(sorted(SECURITY_CONTEXT_SKIP_SUFFIXES)),
        "",
        "## Extension Summary",
    ]
    if extension_summary:
        sections.extend(f"- {suffix}: {count}" for suffix, count in extension_summary)
    else:
        sections.append("- No scannable files found after exclusions.")

    sections.extend([
        "",
        "## File Inventory Preview",
        f"Showing up to {max_inventory} relative paths.",
    ])
    if inventory:
        sections.extend(f"- {item}" for item in inventory)
        if included_count > len(inventory):
            sections.append(f"- ... {included_count - len(inventory)} more files omitted from preview")
    else:
        sections.append("- No scannable files found after exclusions.")

    sections.extend([
        "",
        "## Security Relevant Excerpts",
    ])
    if excerpt_blocks:
        sections.extend(excerpt_blocks)
    else:
        sections.append("Limitation: no security-keyword excerpts were collected from scannable files.")

    sections.extend([
        "",
        "## Notes For Agents",
        "- Use Project Path for direct inspection when available.",
        "- If direct inspection is unavailable, use Security Relevant Excerpts as bounded evidence and state that limitation.",
        "- Real vulnerability evidence should cite project file path, line/function/class/config, and observed behavior.",
    ])

    output_path = ctx.output_dir / "security-context.md"
    ctx.write_text(output_path, "\n".join(sections).strip() + "\n")
