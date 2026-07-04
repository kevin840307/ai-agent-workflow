from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from app.core.paths import atomic_write_text, ensure_dirs


class Store:
    def __init__(
        self,
        path: Path,
        default_project_path: Callable[[], str],
        default_steps: Callable[[], list[dict[str, Any]]],
    ) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._default_project_path = default_project_path
        self._default_steps = default_steps
        self._lock_path = path.with_suffix(path.suffix + ".lock")

    @contextmanager
    def _process_lock(self, timeout_sec: float = 120.0) -> Iterator[None]:
        ensure_dirs()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_sec
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            except FileExistsError:
                if self._lock_can_be_reclaimed():
                    try:
                        self._lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for store lock: {self._lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                self._lock_path.unlink()
            except OSError:
                pass

    def _lock_can_be_reclaimed(self) -> bool:
        try:
            age_sec = time.time() - self._lock_path.stat().st_mtime
        except OSError:
            return False
        holder = self._lock_holder_pid()
        if holder is not None and not self._pid_is_alive(holder):
            return True
        return holder is None and age_sec > 120

    def _lock_holder_pid(self) -> int | None:
        try:
            raw = self._lock_path.read_text(encoding="ascii", errors="ignore").strip()
        except OSError:
            return None
        try:
            pid = int(raw)
        except ValueError:
            return None
        return pid if pid > 0 else None

    def _pid_is_alive(self, pid: int) -> bool:
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _empty(self) -> dict[str, Any]:
        return {"sessions": [], "messages": [], "runs": [], "workflow_configs": []}

    def load_sync(self) -> dict[str, Any]:
        ensure_dirs()
        if not self.path.exists():
            self.save_sync(self._empty())
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            from app.core.paths import utc_now

            backup = self.path.with_suffix(f".corrupt-{utc_now().replace(':', '-')}.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            data = self._empty()
            self.save_sync(data)
        for key in ["sessions", "messages", "runs", "workflow_configs"]:
            if key not in data or not isinstance(data.get(key), list):
                data[key] = []
        changed = False
        for message in data.get("messages", []):
            if "status" not in message:
                message["status"] = "completed"
                changed = True
        for session in data.get("sessions", []):
            if not session.get("qwen_session_id"):
                session["qwen_session_id"] = session["id"]
                changed = True
            if not isinstance(session.get("agent_session_ids"), dict):
                session["agent_session_ids"] = {
                    "qwen": session.get("qwen_session_id") or session["id"],
                    "opencode": session["id"],
                }
                changed = True
            else:
                if "qwen" not in session["agent_session_ids"]:
                    session["agent_session_ids"]["qwen"] = session.get("qwen_session_id") or session["id"]
                    changed = True
                if "opencode" not in session["agent_session_ids"]:
                    session["agent_session_ids"]["opencode"] = session["id"]
                    changed = True
            if not session.get("project_path"):
                session["project_path"] = self._default_project_path()
                changed = True
        for run in data.get("runs", []):
            if not run.get("qwen_session_id"):
                run["qwen_session_id"] = run.get("session_id")
                changed = True
            if not isinstance(run.get("agent_session_ids"), dict):
                run["agent_session_ids"] = {
                    "qwen": run.get("qwen_session_id") or run.get("session_id"),
                    "opencode": run.get("session_id"),
                }
                changed = True
            else:
                if "qwen" not in run["agent_session_ids"]:
                    run["agent_session_ids"]["qwen"] = run.get("qwen_session_id") or run.get("session_id")
                    changed = True
                if "opencode" not in run["agent_session_ids"]:
                    run["agent_session_ids"]["opencode"] = run.get("session_id")
                    changed = True
            for key, default in {
                "status": "queued",
                "error": None,
                "artifacts": [],
                "started_at": None,
                "ended_at": None,
                "created_at": None,
                "updated_at": None,
                "workflow_id": "",
                "workflow_folder": "",
                "workflow_name": "",
                "skill_root": "",
                "test_command": None,
                "validation_script": None,
            }.items():
                if key not in run:
                    run[key] = default
                    changed = True
            if not run.get("steps"):
                run["steps"] = self._default_steps()
                changed = True
            if "timeline" not in run or not isinstance(run.get("timeline"), list):
                run["timeline"] = []
                changed = True
            for step in run.get("steps", []):
                if "retry_count" not in step:
                    step["retry_count"] = 0
                    changed = True
                if "events" not in step or not isinstance(step.get("events"), list):
                    step["events"] = []
                    changed = True
                step.setdefault("status", "pending")
                step.setdefault("started_at", None)
                step.setdefault("ended_at", None)
                step.setdefault("error", None)
        if changed:
            self.save_sync(data)
        return data

    def save_sync(self, data: dict[str, Any]) -> None:
        ensure_dirs()
        atomic_write_text(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    async def mutate(self, fn):
        async with self._lock:
            with self._process_lock():
                data = self.load_sync()
                result = fn(data)
                self.save_sync(data)
            return result

    async def read(self) -> dict[str, Any]:
        async with self._lock:
            with self._process_lock():
                return self.load_sync()
