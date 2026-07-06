from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import HTTPException


# Public names are kept for compatibility with older tests/imports, but runtime
# locks are scoped by event loop. FastAPI TestClient creates a fresh event loop
# per context; reusing asyncio.Lock objects across those loops can stall full
# pytest runs after several workflow tests. Production servers normally use one
# loop, so this remains equivalent there while making tests deterministic.
CHAT_SESSION_LOCKS: dict[str, asyncio.Lock] = {}
PROJECT_RUN_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()

_LOOP_CHAT_SESSION_LOCKS: dict[int, dict[str, asyncio.Lock]] = {}
_LOOP_PROJECT_RUN_LOCKS: dict[int, dict[str, asyncio.Lock]] = {}
_LOOP_LOCKS_GUARDS: dict[int, asyncio.Lock] = {}


def _loop_key() -> int:
    return id(asyncio.get_running_loop())


def _registry_for(kind: str) -> dict[str, asyncio.Lock]:
    key = _loop_key()
    if kind == "chat":
        return _LOOP_CHAT_SESSION_LOCKS.setdefault(key, {})
    if kind == "project":
        return _LOOP_PROJECT_RUN_LOCKS.setdefault(key, {})
    raise ValueError(f"unknown lock registry kind: {kind}")


async def _lock_for(kind: str, key: str) -> asyncio.Lock:
    loop_key = _loop_key()
    guard = _LOOP_LOCKS_GUARDS.setdefault(loop_key, asyncio.Lock())
    async with guard:
        registry = _registry_for(kind)
        lock = registry.get(key)
        if lock is None:
            lock = asyncio.Lock()
            registry[key] = lock
            # Mirror current-loop locks into legacy dictionaries for diagnostics.
            if kind == "chat":
                CHAT_SESSION_LOCKS[key] = lock
            elif kind == "project":
                PROJECT_RUN_LOCKS[key] = lock
        return lock


def normalize_project_lock_key(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


@asynccontextmanager
async def reject_if_chat_busy(session_id: str) -> AsyncIterator[None]:
    lock = await _lock_for("chat", session_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CHAT_SESSION_BUSY",
                "message": "This chat session is already generating an assistant response.",
                "details": {"sessionId": session_id},
            },
        )
    async with lock:
        yield


@asynccontextmanager
async def project_run_creation_lock(project_path: str | Path) -> AsyncIterator[None]:
    key = normalize_project_lock_key(project_path)
    lock = await _lock_for("project", key)
    async with lock:
        yield
