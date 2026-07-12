from __future__ import annotations

from fastapi import Request

from app.core.runtime_context import RuntimeContext, current_runtime_context


def get_runtime_context(request: Request) -> RuntimeContext:
    context = getattr(request.app.state, "runtime_context", None)
    return context if isinstance(context, RuntimeContext) else current_runtime_context()


__all__ = ["get_runtime_context"]
