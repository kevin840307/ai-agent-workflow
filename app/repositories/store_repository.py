from __future__ import annotations

from typing import Any, Callable

from app import runtime


async def read() -> dict[str, Any]:
    return await runtime.store.read()


async def mutate(fn: Callable[[dict[str, Any]], Any]) -> Any:
    return await runtime.store.mutate(fn)
