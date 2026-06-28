from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
