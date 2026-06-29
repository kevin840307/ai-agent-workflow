from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.runtime_modules.paths import ROOT, SETTINGS_FILE, ensure_dirs


def default_settings() -> dict[str, Any]:
    """Return a backward-compatible settings document.

    The original app stored Qwen settings under the ``qwen`` key.  The new
    ``agents`` section is additive, so existing settings files continue to work.
    """
    return {
        "qwen": {
            "auth_type": "",
            "reuse_session": False,
            "max_retries": 2,
        },
        "agents": {
            "default": "qwen",
            "providers": {
                "qwen": {"type": "qwen_cli"},
                "opencode": {
                    "type": "opencode_cli",
                    "bin": "opencode",
                    "mode": "run",
                    "reuseSession": True,
                    "timeoutSec": 1200,
                },
            },
        },
    }


def _apply_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    settings.setdefault("qwen", {})
    settings["qwen"].setdefault("auth_type", "")
    settings["qwen"].setdefault("reuse_session", False)
    settings["qwen"].setdefault("max_retries", 2)

    settings.setdefault("agents", {})
    settings["agents"].setdefault("default", "qwen")
    settings["agents"].setdefault("providers", {})
    settings["agents"]["providers"].setdefault("qwen", {"type": "qwen_cli"})
    settings["agents"]["providers"].setdefault("opencode", {"type": "opencode_cli"})
    settings["agents"]["providers"]["opencode"].setdefault("bin", "opencode")
    settings["agents"]["providers"]["opencode"].setdefault("mode", "run")
    settings["agents"]["providers"]["opencode"].setdefault("reuseSession", True)
    settings["agents"]["providers"]["opencode"].setdefault("timeoutSec", 1200)
    return settings


def load_settings() -> dict[str, Any]:
    ensure_dirs()
    if not SETTINGS_FILE.exists():
        save_settings(default_settings())
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    return _apply_defaults(settings)


def save_settings(settings: dict[str, Any]) -> None:
    ensure_dirs()
    SETTINGS_FILE.write_text(json.dumps(_apply_defaults(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_project_path(project_path: str | None, fallback: Path | None = None) -> Path:
    raw = (project_path or "").strip()
    if not raw:
        return fallback or ROOT
    path = Path(raw).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Project path is not a directory: {path}")
    return path
