from __future__ import annotations

from typing import Any, Callable

from app.core.runtime_context import RuntimeContext, current_runtime_context


def _context(context: RuntimeContext | None = None) -> RuntimeContext:
    return context or current_runtime_context()


async def read(context: RuntimeContext | None = None) -> dict[str, Any]:
    return await _context(context).store.read()


async def mutate(fn: Callable[[dict[str, Any]], Any], context: RuntimeContext | None = None) -> Any:
    return await _context(context).store.mutate(fn)
