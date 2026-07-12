from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from app.core.paths import DATA_DIR, atomic_write_text, utc_now
from app.runtime_modules.files import project_file_snapshot, render_project_index_markdown

_CACHE_DIR = DATA_DIR / "project-index"


def _project_key(project: Path) -> str:
    return hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()[:20]


def _snapshot_digest(snapshot: dict[str, tuple[int, int]]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(snapshot.items()):
        digest.update(path.replace("\\", "/").encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(value[0]).encode("ascii"))
        digest.update(b":")
        digest.update(str(value[1]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def get_cached_project_index(
    project_path: str | Path,
    *,
    renderer: Callable[[Path], str] = render_project_index_markdown,
) -> tuple[str, dict[str, Any]]:
    """Return a read-only project index and reuse it while visible files are unchanged.

    Cache data lives under the controller data directory, never in the user's
    source tree. The file manifest is still checked so agent edits invalidate
    the index deterministically.
    """
    project = Path(project_path).expanduser().resolve()
    snapshot = project_file_snapshot(project)
    digest = _snapshot_digest(snapshot)
    cache_path = _CACHE_DIR / f"{_project_key(project)}.json"
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {}
        if isinstance(cached, dict) and cached.get("snapshot_digest") == digest and isinstance(cached.get("markdown"), str):
            return cached["markdown"], {
                "status": "hit",
                "cache_path": str(cache_path),
                "snapshot_digest": digest,
                "file_count": len(snapshot),
                "generated_at": cached.get("generated_at"),
            }

    markdown = renderer(project)
    payload = {
        "schema": "aiwf.project-index-cache.v1",
        "project_path": str(project),
        "snapshot_digest": digest,
        "file_count": len(snapshot),
        "generated_at": utc_now(),
        "markdown": markdown,
    }
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(cache_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return markdown, {
        "status": "miss",
        "cache_path": str(cache_path),
        "snapshot_digest": digest,
        "file_count": len(snapshot),
        "generated_at": payload["generated_at"],
    }


__all__ = ["get_cached_project_index"]
