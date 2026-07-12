from __future__ import annotations

import filecmp
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from app.core.command_runner import CommandPolicy, CommandRequest, run_command
from typing import Any, Iterable

DEFAULT_IGNORED_DIRS = {
    ".git", ".vs", ".idea", ".vscode", ".claude", ".cursor",
    ".windsurf", ".continue", ".aider", ".codex", ".gemini",
    ".cline", ".roo", ".fleet", ".history", ".ai-workflow",
    "__pycache__", ".pytest_cache", "node_modules", "target", "build", "dist",
}
# Agent configuration directories are intentionally copied so Qwen/OpenCode can
# load project-local config, but they are excluded from Patch Review/delivery.
DEFAULT_CHANGE_IGNORED_DIRS = {
    ".git", ".vs", ".qwen", ".opencode", ".idea", ".vscode",
    ".claude", ".cursor", ".windsurf", ".continue", ".aider",
    ".codex", ".gemini", ".cline", ".roo", ".fleet", ".history",
    ".ai-workflow", ".qwen-workflow", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", ".venv", "venv",
    "target", "build", "dist", ".next", "coverage", "workspaces",
}
IGNORED_DIRS = DEFAULT_IGNORED_DIRS  # compatibility alias
WORKSPACE_POLICY_FILE = Path(".ai-workflow/workspace-policy.json")


def _safe_relative(value: str | Path) -> Path:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return rel


def _iter_project_files(root: Path, *, ignored_dirs: Iterable[str] = DEFAULT_IGNORED_DIRS) -> Iterable[Path]:
    ignored = set(ignored_dirs)
    for path in root.rglob("*"):
        if path.is_file() and not any(part in ignored for part in path.relative_to(root).parts):
            yield path


def load_workspace_policy(project_dir: Path) -> dict[str, Any]:
    """Load structural copy policy; it never inspects requirement or file semantics."""
    project = Path(project_dir).expanduser().resolve()
    policy: dict[str, Any] = {
        "schema": "aiwf.workspace-policy.v1",
        "strategy": str(os.environ.get("AIWF_WORKSPACE_COPY_STRATEGY", "auto") or "auto").lower(),
        "ignored_dirs": sorted(DEFAULT_IGNORED_DIRS),
        "change_ignored_dirs": sorted(DEFAULT_CHANGE_IGNORED_DIRS),
        "max_files": int(os.environ.get("AIWF_WORKSPACE_MAX_FILES", "250000") or 250000),
        "max_bytes": int(os.environ.get("AIWF_WORKSPACE_MAX_BYTES", str(20 * 1024**3)) or 20 * 1024**3),
        "min_free_bytes": int(os.environ.get("AIWF_WORKSPACE_MIN_FREE_BYTES", str(2 * 1024**3)) or 2 * 1024**3),
        "ttl_hours": float(os.environ.get("AIWF_WORKSPACE_TTL_HOURS", "72") or 72),
    }
    path = project / WORKSPACE_POLICY_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"Invalid workspace policy: {path}: {exc}") from exc
        if isinstance(data, dict):
            if data.get("strategy") is not None:
                policy["strategy"] = str(data["strategy"]).strip().lower()
            ignored = data.get("ignoredDirs", data.get("ignored_dirs"))
            if isinstance(ignored, list):
                policy["ignored_dirs"] = sorted({str(item).strip() for item in ignored if str(item).strip()})
            if bool(data.get("includeDependencyDirs", data.get("include_dependency_dirs", False))):
                policy["ignored_dirs"] = [item for item in policy["ignored_dirs"] if item not in {"node_modules", "target", "build", "dist"}]
            change_ignored = data.get("changeIgnoredDirs", data.get("change_ignored_dirs"))
            if isinstance(change_ignored, list):
                policy["change_ignored_dirs"] = sorted({str(item).strip() for item in change_ignored if str(item).strip()})
            additional_change_ignored = data.get("additionalChangeIgnoredDirs", data.get("additional_change_ignored_dirs"))
            if isinstance(additional_change_ignored, list):
                policy["change_ignored_dirs"] = sorted({*policy["change_ignored_dirs"], *(str(item).strip() for item in additional_change_ignored if str(item).strip())})
            for source, target, cast in [
                ("maxFiles", "max_files", int), ("max_files", "max_files", int),
                ("maxBytes", "max_bytes", int), ("max_bytes", "max_bytes", int),
                ("minFreeBytes", "min_free_bytes", int), ("min_free_bytes", "min_free_bytes", int),
                ("ttlHours", "ttl_hours", float), ("ttl_hours", "ttl_hours", float),
            ]:
                if data.get(source) is not None:
                    policy[target] = cast(data[source])
    if policy["strategy"] not in {"auto", "copy", "reflink"}:
        raise ValueError(f"Unsupported workspace copy strategy: {policy['strategy']}")
    return policy


def inspect_workspace_source(project_dir: Path, *, ignored_dirs: Iterable[str]) -> dict[str, int]:
    count = 0
    total = 0
    for path in _iter_project_files(project_dir, ignored_dirs=ignored_dirs):
        count += 1
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return {"file_count": count, "total_bytes": total}


def change_ignored_dirs(project_dir: Path) -> set[str]:
    return set(load_workspace_policy(project_dir).get("change_ignored_dirs") or DEFAULT_CHANGE_IGNORED_DIRS)


def is_change_path_ignored(value: str | Path, *, ignored_dirs: Iterable[str] = DEFAULT_CHANGE_IGNORED_DIRS) -> bool:
    rel = _safe_relative(value)
    ignored = set(ignored_dirs)
    return any(part in ignored for part in rel.parts)


def _iter_change_files(root: Path, *, ignored_dirs: Iterable[str]) -> Iterable[Path]:
    ignored = set(ignored_dirs)
    for path in root.rglob("*"):
        if path.is_file() and not is_change_path_ignored(path.relative_to(root), ignored_dirs=ignored):
            yield path


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def snapshot_project_hashes(project_dir: Path) -> dict[str, str | None]:
    root = Path(project_dir).expanduser().resolve()
    ignored = change_ignored_dirs(root)
    return {path.relative_to(root).as_posix(): file_sha256(path) for path in _iter_change_files(root, ignored_dirs=ignored)}


def create_isolated_project_copy(
    project_dir: Path,
    workspace_dir: Path,
    *,
    ignored_dirs: Iterable[str] | None = None,
    strategy: str | None = None,
) -> Path:
    """Create a run-local project copy while preserving project-local agent config.

    The controller copies bytes only. It never generates or edits production files;
    Qwen/OpenCode run with this copied project as their actual working directory.
    """
    project = Path(project_dir).expanduser().resolve()
    workspace = Path(workspace_dir).expanduser().resolve()
    target = workspace / "agent-project"
    policy = load_workspace_policy(project)
    ignored = set(ignored_dirs if ignored_dirs is not None else policy["ignored_dirs"])
    selected_strategy = str(strategy or policy["strategy"] or "auto").lower()
    source_stats = inspect_workspace_source(project, ignored_dirs=ignored)
    if source_stats["file_count"] > int(policy["max_files"]):
        raise RuntimeError(f"WORKSPACE_FILE_LIMIT: {source_stats['file_count']} > {policy['max_files']}")
    if source_stats["total_bytes"] > int(policy["max_bytes"]):
        raise RuntimeError(f"WORKSPACE_SIZE_LIMIT: {source_stats['total_bytes']} > {policy['max_bytes']}")
    workspace.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(workspace).free
    required = source_stats["total_bytes"] + int(policy["min_free_bytes"])
    if free < required:
        raise RuntimeError(f"WORKSPACE_DISK_SPACE: free={free} required={required}")
    if target.exists():
        shutil.rmtree(target)

    def ignore(_root: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored}

    used_strategy = "copy"
    can_reflink = os.name != "nt" and shutil.which("cp") is not None and not ignored
    if selected_strategy == "reflink" and ignored:
        raise RuntimeError("WORKSPACE_REFLINK_REQUIRES_EMPTY_IGNORE_LIST")
    if selected_strategy in {"auto", "reflink"} and can_reflink:
        target.mkdir(parents=True, exist_ok=True)
        completed = run_command(
            CommandRequest(
                command=["cp", "-a", "--reflink=auto", f"{project}/.", str(target)],
                cwd=workspace,
                project_root=workspace,
                policy=CommandPolicy.TRUSTED,
                timeout_seconds=300,
            )
        )
        if completed.ok:
            used_strategy = "reflink"
        elif selected_strategy == "reflink":
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError(f"WORKSPACE_REFLINK_FAILED: {completed.stderr.strip()[:500]}")
        else:
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(project, target, ignore=ignore)
    else:
        shutil.copytree(project, target, ignore=ignore)

    manifest = {
        "schema": "aiwf.workspace-copy.v1",
        "project": str(project),
        "target": str(target),
        "strategy": used_strategy,
        "ignored_dirs": sorted(ignored),
        **source_stats,
    }
    (workspace / "workspace-copy.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def changed_project_files(original_dir: Path, isolated_dir: Path) -> list[str]:
    """Return deliverable project changes, excluding controller/tool metadata."""
    original = Path(original_dir).expanduser().resolve()
    isolated = Path(isolated_dir).expanduser().resolve()
    ignored = change_ignored_dirs(original)
    paths: set[str] = set()
    for root in [original, isolated]:
        for path in _iter_change_files(root, ignored_dirs=ignored):
            paths.add(path.relative_to(root).as_posix())
    changed: list[str] = []
    for rel in sorted(paths):
        left = original / rel
        right = isolated / rel
        if not left.exists() or not right.exists() or not filecmp.cmp(left, right, shallow=False):
            changed.append(rel)
    return changed


def detect_original_conflicts(
    original_dir: Path,
    changed_files: Iterable[str],
    baseline_hashes: dict[str, str | None] | None,
) -> list[dict[str, Any]]:
    root = Path(original_dir).expanduser().resolve()
    baseline = baseline_hashes or {}
    conflicts: list[dict[str, Any]] = []
    for value in changed_files:
        rel = _safe_relative(value).as_posix()
        expected = baseline.get(rel)
        current = file_sha256(root / rel)
        if current != expected:
            conflicts.append({"path": rel, "expected_sha256": expected, "current_sha256": current})
    return conflicts


def apply_isolated_changes(original_dir: Path, isolated_dir: Path, changed_files: Iterable[str]) -> list[Path]:
    """Compatibility wrapper for applying selected changes."""
    result = apply_isolated_changes_atomic(original_dir, isolated_dir, changed_files)
    return [Path(item) for item in result["written_files"]]


def apply_isolated_changes_atomic(
    original_dir: Path,
    isolated_dir: Path,
    changed_files: Iterable[str],
    *,
    baseline_hashes: dict[str, str | None] | None = None,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    """Atomically synchronize agent-produced changes with rollback evidence.

    Source contents always come from the isolated Qwen/OpenCode workspace. The
    controller only verifies paths, checks conflicts, and performs the final
    synchronization after deterministic validation succeeds.
    """
    original = Path(original_dir).expanduser().resolve()
    isolated = Path(isolated_dir).expanduser().resolve()
    ignored = change_ignored_dirs(original)
    selected = sorted({_safe_relative(item).as_posix() for item in changed_files})
    blocked = [item for item in selected if is_change_path_ignored(item, ignored_dirs=ignored)]
    if blocked:
        raise RuntimeError("ATOMIC_APPLY_IGNORED_PATH: " + json.dumps(blocked, ensure_ascii=False))
    conflicts = detect_original_conflicts(original, selected, baseline_hashes) if baseline_hashes is not None else []
    if conflicts:
        raise RuntimeError("ATOMIC_APPLY_CONFLICT: " + json.dumps(conflicts, ensure_ascii=False))

    owned_backup = backup_dir is None
    backup_root = Path(backup_dir or tempfile.mkdtemp(prefix="aiwf-atomic-backup-")).resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    written: list[str] = []
    deleted: list[str] = []
    try:
        for rel_text in selected:
            rel = Path(rel_text)
            source = (isolated / rel).resolve()
            target = (original / rel).resolve()
            source.relative_to(isolated)
            target.relative_to(original)
            existed = target.is_file()
            backup = backup_root / rel
            if existed:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            manifest.append({"path": rel_text, "existed": existed, "backup": str(backup) if existed else None})

            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".aiwf.tmp", dir=str(target.parent))
                os.close(fd)
                temp_path = Path(temp_name)
                try:
                    shutil.copy2(source, temp_path)
                    os.replace(temp_path, target)
                finally:
                    temp_path.unlink(missing_ok=True)
                written.append(str(target))
            elif target.exists():
                target.unlink()
                deleted.append(str(target))
        return {
            "schema": "aiwf.atomic-apply.v1",
            "status": "applied",
            "written_files": written,
            "deleted_files": deleted,
            "changed_files": selected,
            "backup_dir": str(backup_root),
            "rollback_manifest": manifest,
        }
    except Exception:
        rollback_atomic_apply(original, manifest)
        if owned_backup:
            shutil.rmtree(backup_root, ignore_errors=True)
        raise


def rollback_atomic_apply(original_dir: Path, manifest: Iterable[dict[str, Any]]) -> dict[str, Any]:
    original = Path(original_dir).expanduser().resolve()
    restored: list[str] = []
    removed: list[str] = []
    for item in reversed(list(manifest)):
        rel = _safe_relative(str(item.get("path") or ""))
        target = (original / rel).resolve()
        target.relative_to(original)
        if item.get("existed") and item.get("backup") and Path(item["backup"]).is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(item["backup"]), target)
            restored.append(str(target))
        elif target.exists():
            target.unlink()
            removed.append(str(target))
    return {"schema": "aiwf.atomic-rollback.v1", "restored_files": restored, "removed_files": removed}


__all__ = [
    "apply_isolated_changes", "apply_isolated_changes_atomic", "changed_project_files",
    "create_isolated_project_copy", "detect_original_conflicts", "file_sha256",
    "inspect_workspace_source", "load_workspace_policy", "change_ignored_dirs", "is_change_path_ignored",
    "rollback_atomic_apply", "snapshot_project_hashes",
]
