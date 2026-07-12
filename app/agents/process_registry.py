from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
import ctypes
from collections.abc import MutableMapping, Iterator
from pathlib import Path
from typing import Any

from app.core.paths import DATA_DIR, utc_now, write_text
from app.security.redaction import redact_text


class ProcessRegistry(MutableMapping[str, Any]):
    """Dict-compatible registry with persisted metadata and orphan cleanup."""

    def __init__(self, metadata_path: Path | None = None) -> None:
        self._processes: dict[str, Any] = {}
        self.metadata_path = metadata_path
        self._records: dict[str, dict[str, Any]] = self._load_records()

    def __getitem__(self, key: str) -> Any:
        return self._processes[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.register(key, value)

    def __delitem__(self, key: str) -> None:
        self.unregister(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._processes)

    def __len__(self) -> int:
        return len(self._processes)

    def clear(self) -> None:
        self._processes.clear()
        self._records.clear()
        self._persist()

    def register(self, key: str, process: Any, *, process_type: str = "agent", command: list[str] | None = None, cwd: str | None = None) -> None:
        self._processes[key] = process
        pid = int(getattr(process, "pid", 0) or 0)
        identity = _process_identity(pid)
        controller_identity = _process_identity(os.getpid())
        command_values = [redact_text(str(item))[:240] for item in (command or [])]
        self._records[key] = {
            "schema": "aiwf.managed-process.v2",
            "key": key,
            "pid": pid,
            "process_identity": identity,
            "controller_pid": os.getpid(),
            "controller_identity": controller_identity,
            "process_type": process_type,
            "command": command_values,
            "command_fingerprint": hashlib.sha256((json.dumps(command_values, ensure_ascii=False) + "|" + str(cwd or "") + "|" + str(identity.get("start_key") or "")).encode("utf-8", errors="replace")).hexdigest(),
            "cwd": str(cwd or ""),
            "started_at": utc_now(),
            "managed": True,
        }
        self._persist()

    def unregister(self, key: str, process: Any | None = None) -> None:
        current = self._processes.get(key)
        if process is not None and current is not None and current is not process:
            return
        self._processes.pop(key, None)
        self._records.pop(key, None)
        self._persist()

    def records(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._records.values()]

    def orphan_records(self, *, pid_alive=None, identity_matches=None) -> list[dict[str, Any]]:
        alive = pid_alive or _pid_alive
        matches = identity_matches or _record_identity_matches
        result = []
        stale_keys: list[str] = []
        for key, record in self._records.items():
            pid = int(record.get("pid") or 0)
            controller_pid = int(record.get("controller_pid") or 0)
            if pid <= 0 or not alive(pid):
                stale_keys.append(key)
                continue
            # Tests and custom callers that inject a PID predicate retain the
            # previous deterministic contract. Production always verifies the
            # process creation identity before considering a PID managed.
            if pid_alive is None and not matches(record, controller=False):
                stale_keys.append(key)
                continue
            controller_alive = controller_pid > 0 and alive(controller_pid)
            if controller_alive and pid_alive is None:
                controller_alive = matches(record, controller=True)
            if not controller_alive:
                result.append(dict(record))
        for key in stale_keys:
            self._records.pop(key, None)
        if stale_keys:
            self._persist()
        return result

    def reap_orphans(self, *, terminate=None, pid_alive=None, identity_matches=None) -> list[dict[str, Any]]:
        kill = terminate or _terminate_pid_tree
        reaped: list[dict[str, Any]] = []
        for record in self.orphan_records(pid_alive=pid_alive, identity_matches=identity_matches):
            pid = int(record.get("pid") or 0)
            if pid and kill(pid):
                reaped.append(record)
                self._records.pop(str(record.get("key")), None)
        self._persist()
        return reaped

    def _load_records(self) -> dict[str, dict[str, Any]]:
        if not self.metadata_path or not self.metadata_path.is_file():
            return {}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8-sig"))
            rows = data.get("processes") if isinstance(data, dict) else []
            return {str(item.get("key")): item for item in rows if isinstance(item, dict) and item.get("key")}
        except (OSError, json.JSONDecodeError):
            return {}

    def _persist(self) -> None:
        if not self.metadata_path:
            return
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        write_text(self.metadata_path, json.dumps({"schema": "aiwf.process-registry.v2", "updated_at": utc_now(), "processes": self.records()}, indent=2, ensure_ascii=False))


def _process_identity(pid: int) -> dict[str, Any]:
    if pid <= 0:
        return {"pid": pid, "start_key": None, "executable": None}
    if os.name == "nt":
        return _windows_process_identity(pid)
    start_key = None
    executable = None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        # Field 22 is the process start time in clock ticks. Splitting after the
        # final ')' avoids spaces in the process name corrupting field indexes.
        tail = stat.rsplit(")", 1)[1].strip().split()
        start_key = tail[19] if len(tail) > 19 else None
    except OSError:
        pass
    try:
        executable = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        pass
    return {"pid": pid, "start_key": start_key, "executable": executable}


def _windows_process_identity(pid: int) -> dict[str, Any]:
    process_query_limited_information = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return {"pid": pid, "start_key": None, "executable": None}
    try:
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        start_key = None
        if ctypes.windll.kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)
        ):
            start_key = str(creation.value)
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        executable = buffer.value if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)) else None
        return {"pid": pid, "start_key": start_key, "executable": executable}
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _record_identity_matches(record: dict[str, Any], *, controller: bool = False) -> bool:
    prefix = "controller_" if controller else ""
    pid = int(record.get(f"{prefix}pid") or 0)
    expected = record.get(f"{prefix}identity")
    if not isinstance(expected, dict) or not expected.get("start_key"):
        # Legacy v1 records are not safe to kill automatically. They are kept
        # only until the process exits and then discarded as stale metadata.
        return False
    current = _process_identity(pid)
    return bool(
        current.get("start_key")
        and str(current.get("start_key")) == str(expected.get("start_key"))
        and (not expected.get("executable") or current.get("executable") == expected.get("executable"))
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # Access denied still means the process exists.
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError, SystemError):
        return False


def _terminate_pid_tree(pid: int) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=8)
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                return True
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        return True
    except (ProcessLookupError, OSError, subprocess.SubprocessError):
        return not _pid_alive(pid)


managed_process_registry = ProcessRegistry(Path(os.environ.get("AIWF_PROCESS_REGISTRY_FILE") or (DATA_DIR / "process-registry.json")))


__all__ = ["ProcessRegistry", "managed_process_registry"]
