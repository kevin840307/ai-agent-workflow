from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

# Agent providers are intentionally limited independently. Different sessions may
# run at the same time, while each local endpoint still has a configurable cap.
_LOOP_PROVIDER_SLOTS: dict[int, dict[str, asyncio.Semaphore]] = {}
_LOOP_PROVIDER_LIMITS: dict[int, dict[str, int]] = {}
_LOOP_GUARDS: dict[int, asyncio.Lock] = {}


def _normalize_provider(name: str) -> str:
    value = str(name or "agent").strip().lower().replace("-", "_")
    return value or "agent"


def provider_limit(name: str) -> int:
    provider = _normalize_provider(name)
    specific = os.environ.get(f"AIWF_{provider.upper()}_MAX_CONCURRENCY")
    default = os.environ.get("AIWF_AGENT_MAX_CONCURRENCY", "2")
    try:
        return max(1, min(16, int(specific or default or 2)))
    except (TypeError, ValueError):
        return 2


async def _slot_for(name: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    provider = _normalize_provider(name)
    guard = _LOOP_GUARDS.setdefault(loop_id, asyncio.Lock())
    async with guard:
        slots = _LOOP_PROVIDER_SLOTS.setdefault(loop_id, {})
        limits = _LOOP_PROVIDER_LIMITS.setdefault(loop_id, {})
        limit = provider_limit(provider)
        slot = slots.get(provider)
        if slot is None or limits.get(provider) != limit:
            slot = asyncio.Semaphore(limit)
            slots[provider] = slot
            limits[provider] = limit
        return slot


@asynccontextmanager
async def provider_execution_slot(name: str) -> AsyncIterator[None]:
    """Bound local-provider pressure without serializing unrelated sessions."""
    slot = await _slot_for(name)
    async with slot:
        yield


def provider_slot_snapshot() -> dict[str, dict[str, int]]:
    """Best-effort diagnostics for the current event loop."""
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        return {}
    slots = _LOOP_PROVIDER_SLOTS.get(loop_id, {})
    limits = _LOOP_PROVIDER_LIMITS.get(loop_id, {})
    return {
        name: {
            "limit": limits.get(name, provider_limit(name)),
            "available": int(getattr(slot, "_value", 0)),
        }
        for name, slot in slots.items()
    }


__all__ = ["provider_execution_slot", "provider_limit", "provider_slot_snapshot"]
