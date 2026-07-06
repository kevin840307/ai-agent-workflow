from __future__ import annotations

import os
import sys
from pathlib import Path


# Test runs must not share the application store with manual/dev runs or with
# previous pytest invocations. The workflow API module binds its Store at import
# time, so configure the test-only store here before any test imports app.*.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_DATA_DIR = _REPO_ROOT / "data" / "pytest"
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("AIWF_STORE_FILE", str(_TEST_DATA_DIR / f"store-{os.getpid()}.json"))
os.environ.setdefault("QWEN_USE_SERVE", "0")
os.environ.setdefault("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", "0")


def _reset_runtime_state() -> None:
    runtime = sys.modules.get("app.runtime_modules.api")
    if runtime is not None:
        for task in list(getattr(runtime, "running_tasks", {}).values()):
            if not task.done():
                task.cancel()
        getattr(runtime, "running_tasks", {}).clear()
        getattr(runtime, "running_processes", {}).clear()
        store = getattr(runtime, "store", None)
        if store is not None:
            store.save_sync({"sessions": [], "messages": [], "runs": [], "workflow_configs": []})

    locks = sys.modules.get("app.core.locks")
    if locks is not None:
        for name in (
            "CHAT_SESSION_LOCKS",
            "PROJECT_RUN_LOCKS",
            "_LOOP_CHAT_SESSION_LOCKS",
            "_LOOP_PROJECT_RUN_LOCKS",
            "_LOOP_LOCKS_GUARDS",
        ):
            registry = getattr(locks, name, None)
            if hasattr(registry, "clear"):
                registry.clear()


def pytest_runtest_setup(item):  # noqa: ANN001 - pytest hook signature
    _reset_runtime_state()


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001 - pytest hook signature
    _reset_runtime_state()
