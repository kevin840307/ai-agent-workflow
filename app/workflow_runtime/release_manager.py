from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.paths import DATA_DIR, ROOT, utc_now, write_text

APP_VERSION = "1.9.0"
DATABASE_SCHEMA_VERSION = 9
WORKFLOW_SCHEMA_VERSION = 6
CONFIG_SCHEMA_VERSION = 5


def version_manifest() -> dict[str, Any]:
    return {
        "app_version": APP_VERSION,
        "database_schema": DATABASE_SCHEMA_VERSION,
        "workflow_schema": WORKFLOW_SCHEMA_VERSION,
        "config_schema": CONFIG_SCHEMA_VERSION,
        "generated_at": utc_now(),
    }


def write_version_manifest(root: Path | None = None) -> Path:
    target = (root or ROOT) / "data" / "version.json"
    write_text(target, json.dumps(version_manifest(), indent=2, ensure_ascii=False))
    return target


def create_upgrade_backup(store_path: Path) -> Path:
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "-")
    target = backup_dir / f"{store_path.stem}-{stamp}{store_path.suffix}.bak"
    shutil.copy2(store_path, target)
    return target


def upgrade_readiness(store_path: Path | None = None) -> dict[str, Any]:
    store = store_path or (DATA_DIR / "store.sqlite3")
    return {
        "schema": "aiwf.upgrade-readiness.v1",
        "version": version_manifest(),
        "store_path": str(store),
        "store_exists": store.exists(),
        "backup_supported": True,
        "steps": [
            "Stop active runs and create a SQLite backup.",
            "Validate database/config/workflow schema versions.",
            "Apply forward-only migrations.",
            "Run setup smoke and workflow asset validation.",
            "Start the controller; restore the backup if validation fails.",
        ],
    }


__all__ = ["APP_VERSION", "CONFIG_SCHEMA_VERSION", "DATABASE_SCHEMA_VERSION", "WORKFLOW_SCHEMA_VERSION", "create_upgrade_backup", "upgrade_readiness", "version_manifest", "write_version_manifest"]
