from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

from app.core.paths import read_text, write_text

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".sql", ".csv"
}
IGNORE_DIRS = {".ai-workflow", ".qwen-workflow", ".qwen", ".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
MAX_FILE_CHARS = 80_000


def _should_skip(path: Path, project_dir: Path) -> bool:
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return True
    parts = set(rel.parts)
    if parts & IGNORE_DIRS:
        return True
    return False


def snapshot_project_text(project_dir: Path) -> dict[str, str]:
    project_dir = project_dir.resolve()
    snapshot: dict[str, str] = {}
    if not project_dir.exists():
        return snapshot
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or _should_skip(path, project_dir):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n# ... truncated by ai-workflow diff snapshot ...\n"
        snapshot[path.relative_to(project_dir).as_posix()] = text
    return snapshot


def write_baseline_snapshot(run: dict[str, Any], run_dir: Path) -> None:
    project = Path(run.get("project_path") or run_dir)
    payload = {
        "schema": "aiwf.project-text-snapshot.v1",
        "project_path": str(project),
        "files": snapshot_project_text(project),
    }
    write_text(run_dir / ".workflow" / "project-snapshot-before.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _load_baseline(run_dir: Path) -> dict[str, str]:
    path = run_dir / ".workflow" / "project-snapshot-before.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    files = payload.get("files") if isinstance(payload, dict) else {}
    return files if isinstance(files, dict) else {}


def build_run_diff(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    before = _load_baseline(run_dir)
    after = snapshot_project_text(Path(run.get("project_path") or run_dir))
    paths = sorted(set(before) | set(after))
    files: list[dict[str, Any]] = []
    patch_chunks: list[str] = []
    for rel in paths:
        old = before.get(rel)
        new = after.get(rel)
        if old == new:
            continue
        status = "modified"
        if old is None:
            status = "added"
        elif new is None:
            status = "deleted"
        old_lines = (old or "").splitlines(keepends=True)
        new_lines = (new or "").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
        files.append({"path": rel, "status": status, "added_lines": max(0, len(new_lines) - len(old_lines)), "deleted_lines": max(0, len(old_lines) - len(new_lines))})
        if diff:
            patch_chunks.append(diff)
    return {
        "schema": "aiwf.run-diff.v1",
        "run_id": run.get("id"),
        "project_path": run.get("project_path"),
        "file_count": len(files),
        "files": files,
        "patch": "\n".join(patch_chunks),
    }


def render_run_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        "# Run Diff",
        "",
        f"- Run ID: {diff.get('run_id')}",
        f"- Project Path: {diff.get('project_path')}",
        f"- Changed Files: {diff.get('file_count', 0)}",
        "",
        "## Files",
    ]
    files = diff.get("files") or []
    if files:
        for item in files:
            lines.append(f"- `{item.get('path')}` - {item.get('status')} (+{item.get('added_lines', 0)} / -{item.get('deleted_lines', 0)})")
    else:
        lines.append("- No text file changes detected outside workflow internals.")
    if diff.get("patch"):
        lines.extend(["", "## Patch", "", "```diff", str(diff.get("patch"))[:200_000], "```"])
    return "\n".join(lines).rstrip() + "\n"


def write_run_diff_artifacts(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    workflow_dir = run_dir / ".workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    diff = build_run_diff(run, run_dir)
    write_text(workflow_dir / "run-diff.json", json.dumps(diff, indent=2, ensure_ascii=False))
    write_text(workflow_dir / "run-diff.md", render_run_diff_markdown(diff))
    return diff


__all__ = ["snapshot_project_text", "write_baseline_snapshot", "build_run_diff", "write_run_diff_artifacts", "render_run_diff_markdown"]
