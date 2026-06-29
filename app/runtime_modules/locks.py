from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import HTTPException


CHAT_SESSION_LOCKS: dict[str, asyncio.Lock] = {}
PROJECT_RUN_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


async def _lock_for(registry: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        lock = registry.get(key)
        if lock is None:
            lock = asyncio.Lock()
            registry[key] = lock
        return lock


def normalize_project_lock_key(path: str | Path) -> str:
    return str(Path(path).resolve()).casefold()


@asynccontextmanager
async def reject_if_chat_busy(session_id: str) -> AsyncIterator[None]:
    lock = await _lock_for(CHAT_SESSION_LOCKS, session_id)
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
    lock = await _lock_for(PROJECT_RUN_LOCKS, key)
    async with lock:
        yield

