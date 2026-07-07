from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from app.core.paths import ensure_dirs


class SQLiteStore:
    """SQLite-backed implementation with the same read/mutate contract as Store.

    The first SQLite backend intentionally stores the canonical document as a
    single JSON blob.  That keeps the migration risk low while giving production
    pilots a transactional backend, process-safe locking, and a stable seam for
    future normalized runs/steps/events tables.
    """

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
        self._busy_timeout_ms = int(float(os.environ.get("AIWF_SQLITE_BUSY_TIMEOUT_SEC", "30") or 30) * 1000)
        ensure_dirs()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=max(1, self._busy_timeout_ms / 1000), isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_documents "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
            )
            existing = conn.execute("SELECT 1 FROM store_documents WHERE key='state'").fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?)",
                    (json.dumps(self._empty(), ensure_ascii=False), time.time()),
                )

    def _empty(self) -> dict[str, Any]:
        return {"sessions": [], "messages": [], "runs": [], "workflow_configs": []}

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
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
                session["qwen_session_id"] = session.get("id")
                changed = True
            if not session.get("project_path"):
                session["project_path"] = self._default_project_path()
                changed = True
            if not isinstance(session.get("agent_session_ids"), dict):
                session["agent_session_ids"] = {
                    "qwen": session.get("qwen_session_id") or session.get("id"),
                    "opencode": session.get("id"),
                }
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
                step.setdefault("error_code", None)
        return data

    def load_sync(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM store_documents WHERE key='state'").fetchone()
        if not row:
            data = self._empty()
            self.save_sync(data)
            return data
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            data = self._empty()
            self.save_sync(data)
        return self._normalize(data)

    def save_sync(self, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (json.dumps(data, indent=2, ensure_ascii=False), time.time()),
            )
            conn.execute("COMMIT")

    async def read(self) -> dict[str, Any]:
        async with self._lock:
            return self.load_sync()

    async def mutate(self, fn):
        async with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT value FROM store_documents WHERE key='state'").fetchone()
                data = json.loads(row[0]) if row else self._empty()
                data = self._normalize(data)
                result = fn(data)
                conn.execute(
                    "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (json.dumps(data, indent=2, ensure_ascii=False), time.time()),
                )
                conn.execute("COMMIT")
                return result
