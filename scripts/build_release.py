from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "data" / "version.json"

TOP_LEVEL_FILES = {
    ".gitignore",
    ".python-version",
    "README.md",
    "pytest.ini",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-browser.txt",
    "constraints-tested.txt",
    "constraints-dev-tested.txt",
    "constraints-browser-tested.txt",
    "IMPLEMENTATION_REPORT_V23.md",
    "IMPLEMENTATION_REPORT_V24.md",
    "IMPLEMENTATION_REPORT_V24_1.md",
    "CHANGELOG.md",
    "UPGRADE.md",
    "MIGRATIONS.md",
}
TOP_LEVEL_DIRS = {
    "app",
    "static",
    "scripts",
    "tests",
    "doc",
    "docs",
    "examples",
}
RUNTIME_EXCLUDED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    ".git",
    ".vs",
    ".venv",
    "venv",
    "node_modules",
    "test-results",
    "reports",
    "workspaces",
    "dist",
}
RUNTIME_DATA_DIRS = {
    "project-index",
    "pytest",
    "project-validation-profiles",
    "model-capabilities",
    "provider-connectivity",
}
RUNTIME_FILE_PREFIXES = (
    "store",
    "process-registry",
    "settings",
)
ALLOWED_DATA_ROOTS = {
    PurePosixPath("data/version.json"),
    PurePosixPath("data/agent-commands"),
    PurePosixPath("data/ai-workflow/WORKFLOW_CONTRACT_SCHEMA.md"),
    PurePosixPath("data/ai-workflow/contracts"),
    PurePosixPath("data/ai-workflow/functions"),
    PurePosixPath("data/ai-workflow/steps"),
    PurePosixPath("data/ai-workflow/workflows"),
}


@dataclass(frozen=True)
class ReleaseFile:
    path: Path
    archive_path: PurePosixPath
    size: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_allowed_data_path(relative: PurePosixPath) -> bool:
    if relative == PurePosixPath("data/version.json"):
        return True
    if len(relative.parts) >= 2 and relative.parts[:2] == ("data", "agent-commands"):
        return PurePosixPath("data/agent-commands") in relative.parents
    if len(relative.parts) < 3 or relative.parts[:2] != ("data", "ai-workflow"):
        return False
    if any(part in RUNTIME_DATA_DIRS for part in relative.parts):
        return relative.name == ".gitkeep"
    return any(relative == root or root in relative.parents for root in ALLOWED_DATA_ROOTS)


def _is_release_file(path: Path) -> bool:
    if not path.is_file():
        return False
    relative = PurePosixPath(path.relative_to(ROOT).as_posix())
    if any(part in RUNTIME_EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() in {".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".wal", ".shm"}:
        return False
    if relative.parts[0] == "data":
        if len(relative.parts) == 2 and relative.name.startswith(RUNTIME_FILE_PREFIXES):
            return False
        return _is_allowed_data_path(relative)
    if len(relative.parts) == 1:
        return relative.name in TOP_LEVEL_FILES
    return relative.parts[0] in TOP_LEVEL_DIRS


def collect_release_files() -> list[ReleaseFile]:
    candidates: list[Path] = []
    for filename in sorted(TOP_LEVEL_FILES):
        path = ROOT / filename
        if path.exists():
            candidates.append(path)
    for dirname in sorted(TOP_LEVEL_DIRS | {"data"}):
        path = ROOT / dirname
        if path.exists():
            candidates.extend(sorted(item for item in path.rglob("*") if item.is_file()))

    result: list[ReleaseFile] = []
    seen: set[PurePosixPath] = set()
    for path in candidates:
        if not _is_release_file(path):
            continue
        archive_path = PurePosixPath(path.relative_to(ROOT).as_posix())
        if archive_path in seen:
            continue
        seen.add(archive_path)
        result.append(ReleaseFile(path, archive_path, path.stat().st_size, _sha256(path)))
    return sorted(result, key=lambda item: item.archive_path.as_posix())


def _load_version() -> dict[str, object]:
    try:
        payload = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def build_manifest(files: Iterable[ReleaseFile]) -> dict[str, object]:
    file_list = list(files)
    version = _load_version()
    generated_at = str(version.get("generated_at") or os.environ.get("SOURCE_DATE_EPOCH") or "unknown")
    return {
        "schema": "aiwf.release-manifest.v1",
        "app_version": str(version.get("app_version") or "unknown"),
        "generated_at": generated_at,
        "python": {
            "supported": ">=3.10,<3.13",
            "build_interpreter": sys.version.split()[0],
        },
        "checks": {
            "allowlist_packaging": True,
            "runtime_state_excluded": True,
            "per_file_sha256": True,
        },
        "file_count": len(file_list),
        "total_bytes": sum(item.size for item in file_list),
        "files": [
            {"path": item.archive_path.as_posix(), "size": item.size, "sha256": item.sha256}
            for item in file_list
        ],
    }


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def write_release(output: Path) -> tuple[Path, dict[str, object]]:
    files = collect_release_files()
    manifest = build_manifest(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in files:
            archive.writestr(_zip_info(item.archive_path.as_posix()), item.path.read_bytes())
        archive.writestr(
            _zip_info("RELEASE_MANIFEST.json"),
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n",
        )
    sidecar = output.with_suffix(output.suffix + ".manifest.json")
    sidecar.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, manifest


def validate_release_inputs() -> list[str]:
    errors: list[str] = []
    required = [
        "README.md",
        "requirements.txt",
        "data/version.json",
        "data/ai-workflow/WORKFLOW_CONTRACT_SCHEMA.md",
        "data/agent-commands/qwen/commands/wf.md",
        "data/agent-commands/qwen/commands/wstep.md",
        "data/agent-commands/opencode/commands/wf.md",
        "data/agent-commands/opencode/commands/wstep.md",
        "app/main.py",
        "static/index.html",
    ]
    for relative in required:
        if not (ROOT / relative).exists():
            errors.append(f"missing required release input: {relative}")
    files = collect_release_files()
    if not files:
        errors.append("release allowlist produced no files")
    forbidden = [
        item.archive_path.as_posix()
        for item in files
        if any(part in RUNTIME_EXCLUDED_PARTS | RUNTIME_DATA_DIRS for part in item.archive_path.parts)
        and item.archive_path.name != ".gitkeep"
    ]
    if forbidden:
        errors.extend(f"forbidden release path: {path}" for path in forbidden)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean, allowlisted AI Workflow release ZIP.")
    parser.add_argument("--output", type=Path, help="Output ZIP path. Defaults to dist/ai-workflow-<version>.zip")
    parser.add_argument("--check-only", action="store_true", help="Validate release inputs without writing a ZIP.")
    args = parser.parse_args()

    errors = validate_release_inputs()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    files = collect_release_files()
    if args.check_only:
        print(json.dumps({"ok": True, "file_count": len(files), "total_bytes": sum(item.size for item in files)}, indent=2))
        return 0

    version = _load_version()
    output = args.output or ROOT / "dist" / f"ai-workflow-{version.get('app_version', 'dev')}.zip"
    output, manifest = write_release(output.resolve())
    print(json.dumps({"ok": True, "output": str(output), "file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
