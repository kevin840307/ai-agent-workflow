from __future__ import annotations

import ctypes
import os
import socket
from typing import Any

from app.core.paths import utc_now


_PROCESS_STARTED_AT = utc_now()


def current_run_owner() -> dict[str, Any]:
    host = socket.gethostname()
    pid = os.getpid()
    return {
        "id": f"{host}:{pid}",
        "host": host,
        "pid": pid,
        "started_at": _PROCESS_STARTED_AT,
    }


def owner_matches_current_process(owner: Any) -> bool:
    if not isinstance(owner, dict):
        return False
    current = current_run_owner()
    return owner.get("id") == current["id"] or (
        owner.get("host") == current["host"] and int(owner.get("pid") or -1) == current["pid"]
    )


def owner_process_is_alive(owner: Any) -> bool:
    if not isinstance(owner, dict):
        return False
    if str(owner.get("host") or "") != socket.gethostname():
        return True
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    return _posix_process_is_alive(pid)


def _posix_process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_process_is_alive(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    synchronize = 0x00100000
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(synchronize | process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        wait_timeout = 0x00000102
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)
