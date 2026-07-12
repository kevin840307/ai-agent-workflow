from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, MutableMapping


class RuntimeContext:
    """Explicit container for controller-owned runtime services.

    ``app.runtime_modules.api`` remains a compatibility facade. New services,
    routes, and tests should receive this object explicitly or resolve it via
    ``current_runtime_context``. Optional providers let the compatibility facade
    keep legacy monkey-patching behavior without forcing new code to import its
    mutable module globals.
    """

    def __init__(
        self,
        *,
        store: Any,
        bus: Any,
        run_state: Any,
        running_tasks: MutableMapping[str, Any],
        running_processes: Any,
        agent_manager: Any,
        workflow_actions: Any,
        workflow_executor: Any,
        workflow_kernel: Any,
        store_provider: Any = None,
        bus_provider: Any = None,
        running_tasks_provider: Any = None,
        running_processes_provider: Any = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self.run_state = run_state
        self._running_tasks = running_tasks
        self._running_processes = running_processes
        self.agent_manager = agent_manager
        self.workflow_actions = workflow_actions
        self.workflow_executor = workflow_executor
        self.workflow_kernel = workflow_kernel
        self._store_provider = store_provider
        self._bus_provider = bus_provider
        self._running_tasks_provider = running_tasks_provider
        self._running_processes_provider = running_processes_provider

    @property
    def store(self) -> Any:
        return self._store_provider() if callable(self._store_provider) else self._store

    @property
    def bus(self) -> Any:
        return self._bus_provider() if callable(self._bus_provider) else self._bus

    @property
    def running_tasks(self) -> MutableMapping[str, Any]:
        return self._running_tasks_provider() if callable(self._running_tasks_provider) else self._running_tasks

    @property
    def running_processes(self) -> Any:
        return self._running_processes_provider() if callable(self._running_processes_provider) else self._running_processes

    def active_task_count(self) -> int:
        return sum(1 for task in self.running_tasks.values() if task is not None and not task.done())

    def process_count(self) -> int:
        try:
            return len(self.running_processes)
        except TypeError:
            return len(list(self.running_processes.values()))

    def store_path(self) -> Path:
        return Path(self.store.path)

    def store_backend_name(self) -> str:
        return "sqlite" if self.store.__class__.__name__ == "SQLiteStore" else "file"


_default_context: RuntimeContext | None = None
_context_override: ContextVar[RuntimeContext | None] = ContextVar("aiwf_runtime_context", default=None)


def install_runtime_context(context: RuntimeContext) -> RuntimeContext:
    """Install the process-wide controller context once during composition."""
    global _default_context
    _default_context = context
    return context


def current_runtime_context() -> RuntimeContext:
    context = _context_override.get() or _default_context
    if context is None:
        raise RuntimeError("RUNTIME_CONTEXT_NOT_INSTALLED")
    return context


@contextmanager
def use_runtime_context(context: RuntimeContext) -> Iterator[RuntimeContext]:
    """Temporarily override runtime services for one test or isolated operation."""
    token = _context_override.set(context)
    try:
        yield context
    finally:
        _context_override.reset(token)


__all__ = [
    "RuntimeContext",
    "current_runtime_context",
    "install_runtime_context",
    "use_runtime_context",
]
