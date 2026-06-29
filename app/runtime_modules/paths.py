from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
WORKSPACES_DIR = ROOT / "workspaces"
STATIC_DIR = ROOT / "static"
WORKFLOW_BUNDLES_DIR = DATA_DIR / "workflows"
SYSTEM_WORKFLOW_ID = "system-controlled-qwen"
STORE_FILE = DATA_DIR / "store.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_SKILL_PATH = Path.home() / ".qwen" / "skills"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    WORKSPACES_DIR.mkdir(exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Directory fsync is not supported on every platform/filesystem.
            pass
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise


def write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)
