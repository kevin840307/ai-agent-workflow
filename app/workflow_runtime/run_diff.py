from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Iterable

from app.core.paths import read_text, write_text
from app.security.isolated_workspace import DEFAULT_CHANGE_IGNORED_DIRS, change_ignored_dirs, is_change_path_ignored

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".sql", ".csv"
}
MAX_FILE_CHARS = 80_000


def _should_skip(path: Path, project_dir: Path, *, ignored_dirs: Iterable[str]) -> bool:
    try:
        rel = path.relative_to(project_dir)
    except ValueError:
        return True
    return is_change_path_ignored(rel, ignored_dirs=ignored_dirs)


def snapshot_project_text(project_dir: Path, *, ignored_dirs: Iterable[str] | None = None) -> dict[str, str]:
    project_dir = project_dir.resolve()
    ignored = set(ignored_dirs or change_ignored_dirs(project_dir) or DEFAULT_CHANGE_IGNORED_DIRS)
    snapshot: dict[str, str] = {}
    if not project_dir.exists():
        return snapshot
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or _should_skip(path, project_dir, ignored_dirs=ignored):
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
    policy_root = Path(run.get("original_project_path") or project)
    ignored = change_ignored_dirs(policy_root)
    payload = {
        "schema": "aiwf.project-text-snapshot.v1",
        "project_path": str(project),
        "ignored_dirs": sorted(ignored),
        "files": snapshot_project_text(project, ignored_dirs=ignored),
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


def _line_change_counts(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]:
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    added = 0
    removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            added += j2 - j1
        if tag in {"delete", "replace"}:
            removed += i2 - i1
    return added, removed


def build_run_diff(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    project = Path(run.get("project_path") or run_dir)
    policy_root = Path(run.get("original_project_path") or project)
    ignored = change_ignored_dirs(policy_root)
    before = {path: content for path, content in _load_baseline(run_dir).items() if not is_change_path_ignored(path, ignored_dirs=ignored)}
    after = snapshot_project_text(project, ignored_dirs=ignored)
    paths = sorted(set(before) | set(after))
    files: list[dict[str, Any]] = []
    patch_chunks: list[str] = []
    total_added = 0
    total_removed = 0
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
        old_lines = (old or "").splitlines()
        new_lines = (new or "").splitlines()
        added, removed = _line_change_counts(old_lines, new_lines)
        patch = "\n".join(
            difflib.unified_diff(
                old_lines, new_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""
            )
        )
        item = {
            "path": rel,
            "status": status,
            "added": added,
            "removed": removed,
            "added_lines": added,
            "deleted_lines": removed,
            "old_line_count": len(old_lines),
            "new_line_count": len(new_lines),
            "patch": patch,
        }
        files.append(item)
        total_added += added
        total_removed += removed
        if patch:
            patch_chunks.append(patch)
    return {
        "schema": "aiwf.run-diff.v2",
        "run_id": run.get("id"),
        "project_path": run.get("project_path"),
        "file_count": len(files),
        "summary": {"files": len(files), "added": total_added, "removed": total_removed},
        "files": files,
        "patch": "\n".join(patch_chunks),
        "ignored_dirs": sorted(ignored),
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
            lines.append(f"- `{item.get('path')}` - {item.get('status')} (+{item.get('added', item.get('added_lines', 0))} / -{item.get('removed', item.get('deleted_lines', 0))})")
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
