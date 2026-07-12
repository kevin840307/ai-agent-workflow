from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from app.core.paths import ensure_dirs


SCHEMA_VERSION = 3


class SQLiteStore:
    """Transactional SQLite store with backward-compatible document state.

    `store_documents.state` remains the compatibility source for the existing
    runtime. Every commit also refreshes normalized projection tables for runs,
    steps, tasks, sessions, events, artifacts, validation evidence, file
    changes, checkpoints, and project locks. New UI/reporting code can query
    structured data without reparsing the whole JSON document.
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
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS store_documents "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            self._create_projection_tables(conn)
            for version in range(1, SCHEMA_VERSION + 1):
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (version, time.time()),
                )
            existing = conn.execute("SELECT 1 FROM store_documents WHERE key='state'").fetchone()
            if not existing:
                empty = self._empty()
                conn.execute(
                    "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?)",
                    (json.dumps(empty, ensure_ascii=False), time.time()),
                )
                self._sync_projections(conn, empty)

    def _create_projection_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                workflow_id TEXT,
                workflow_name TEXT,
                project_path TEXT,
                status TEXT NOT NULL,
                phase TEXT,
                error_code TEXT,
                error TEXT,
                created_at TEXT,
                started_at TEXT,
                ended_at TEXT,
                updated_at TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
            CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_path, created_at);

            CREATE TABLE IF NOT EXISTS run_steps (
                run_id TEXT NOT NULL,
                step_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                title TEXT,
                status TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                error TEXT,
                started_at TEXT,
                ended_at TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, step_key),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_steps_status ON run_steps(run_id, status);

            CREATE TABLE IF NOT EXISTS tasks (
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                title TEXT,
                status TEXT,
                position INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, task_id),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_sessions (
                run_id TEXT NOT NULL,
                role TEXT NOT NULL,
                agent TEXT NOT NULL,
                session_id TEXT,
                status TEXT,
                updated_at TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, role, agent),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_key TEXT,
                event_type TEXT,
                message TEXT,
                occurred_at TEXT,
                event_key TEXT,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, id);

            CREATE TABLE IF NOT EXISTS run_artifacts (
                run_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                path TEXT,
                category TEXT,
                role TEXT,
                visibility TEXT,
                size_bytes INTEGER,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, artifact_id),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS validation_results (
                run_id TEXT NOT NULL,
                validation_key TEXT NOT NULL,
                status TEXT,
                command TEXT,
                exit_code INTEGER,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, validation_key),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS file_changes (
                run_id TEXT NOT NULL,
                path TEXT NOT NULL,
                change_type TEXT,
                additions INTEGER,
                deletions INTEGER,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, path),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                step_key TEXT,
                status TEXT,
                created_at TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(run_id, checkpoint_id),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_locks (
                project_path TEXT PRIMARY KEY,
                run_id TEXT,
                mode TEXT,
                acquired_at TEXT,
                payload_json TEXT NOT NULL
            );
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(run_events)").fetchall()}
        if "event_key" not in columns:
            conn.execute("ALTER TABLE run_events ADD COLUMN event_key TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_key ON run_events(run_id, event_key)")

    def _empty(self) -> dict[str, Any]:
        return {"state_version": 0, "sessions": [], "messages": [], "runs": [], "workflow_configs": []}

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data["state_version"] = int(data.get("state_version") or 0)
        for key in ["sessions", "messages", "runs", "workflow_configs"]:
            if key not in data or not isinstance(data.get(key), list):
                data[key] = []
        for message in data.get("messages", []):
            message.setdefault("status", "completed")
        for session in data.get("sessions", []):
            session.setdefault("qwen_session_id", session.get("id"))
            session.setdefault("project_path", self._default_project_path())
            if not isinstance(session.get("agent_session_ids"), dict):
                session["agent_session_ids"] = {
                    "qwen": session.get("qwen_session_id") or session.get("id"),
                    "opencode": session.get("id"),
                }
        for run in data.get("runs", []):
            run.setdefault("qwen_session_id", run.get("session_id"))
            if not isinstance(run.get("agent_session_ids"), dict):
                run["agent_session_ids"] = {
                    "qwen": run.get("qwen_session_id") or run.get("session_id"),
                    "opencode": run.get("session_id"),
                }
            for key, default in {
                "status": "queued", "error": None, "artifacts": [], "started_at": None,
                "ended_at": None, "created_at": None, "updated_at": None, "workflow_id": "",
                "workflow_folder": "", "workflow_name": "", "skill_root": "", "test_command": None,
                "validation_script": None, "timeline": [], "tasks": [], "checkpoints": [],
                "validation_results": [], "file_changes": [], "transitions": [],
            }.items():
                if key not in run or (key in {"artifacts", "timeline", "tasks", "checkpoints", "validation_results", "file_changes", "transitions"} and not isinstance(run.get(key), list)):
                    run[key] = default.copy() if isinstance(default, list) else default
            if not run.get("steps"):
                run["steps"] = self._default_steps()
            for step in run.get("steps", []):
                step.setdefault("retry_count", 0)
                if not isinstance(step.get("events"), list):
                    step["events"] = []
                step.setdefault("status", "pending")
                step.setdefault("started_at", None)
                step.setdefault("ended_at", None)
                step.setdefault("error", None)
                step.setdefault("error_code", None)
                if not isinstance(step.get("transitions"), list):
                    step["transitions"] = []
        return data

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _projection_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        if isinstance(value, (dict, set)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return str(value)

    @staticmethod
    def _event_key(run_id: str, event: dict[str, Any]) -> str:
        raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(f"{run_id}|{raw}".encode("utf-8", errors="replace")).hexdigest()

    def _insert_event(self, conn: sqlite3.Connection, run_id: str, event: dict[str, Any], *, step_key: str | None = None) -> None:
        payload = self._json(event)
        conn.execute(
            "INSERT OR IGNORE INTO run_events(run_id,step_key,event_type,message,occurred_at,event_key,payload_json) VALUES(?,?,?,?,?,?,?)",
            (
                run_id,
                step_key or event.get("step_key") or event.get("stepKey"),
                event.get("kind") or event.get("type"),
                event.get("message"),
                event.get("at") or event.get("time") or event.get("ts"),
                self._event_key(run_id, event),
                payload,
            ),
        )

    def _sync_run_projection(self, conn: sqlite3.Connection, run: dict[str, Any]) -> None:
        run_id = str(run.get("id") or "")
        if not run_id:
            return
        current_step = next((step for step in run.get("steps", []) if step.get("status") in {"running", "waiting_input"}), None)
        phase = run.get("phase") or (current_step or {}).get("phase") or run.get("status")
        conn.execute(
            "INSERT INTO runs(id,session_id,workflow_id,workflow_name,project_path,status,phase,error_code,error,created_at,started_at,ended_at,updated_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET session_id=excluded.session_id,workflow_id=excluded.workflow_id,workflow_name=excluded.workflow_name,project_path=excluded.project_path,status=excluded.status,phase=excluded.phase,error_code=excluded.error_code,error=excluded.error,created_at=excluded.created_at,started_at=excluded.started_at,ended_at=excluded.ended_at,updated_at=excluded.updated_at,payload_json=excluded.payload_json",
            (run_id, run.get("session_id"), run.get("workflow_id"), run.get("workflow_name"), run.get("original_project_path") or run.get("project_path"), run.get("status") or "queued", phase, run.get("error_code"), run.get("error"), run.get("created_at"), run.get("started_at"), run.get("ended_at"), run.get("updated_at"), self._json(run)),
        )
        for table in ("run_artifacts", "validation_results", "file_changes", "checkpoints", "agent_sessions", "tasks", "run_steps"):
            conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM project_locks WHERE run_id=?", (run_id,))

        for position, step in enumerate(run.get("steps") or []):
            key = str(step.get("key") or f"step-{position}")
            conn.execute(
                "INSERT INTO run_steps(run_id,step_key,position,title,status,retry_count,error_code,error,started_at,ended_at,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, key, position, step.get("title") or step.get("name") or key, step.get("status"), int(step.get("retry_count") or 0), step.get("error_code"), step.get("error"), step.get("started_at"), step.get("ended_at"), self._json(step)),
            )
            for event in step.get("events") or []:
                if isinstance(event, dict):
                    self._insert_event(conn, run_id, event, step_key=key)
        for position, task in enumerate(run.get("tasks") or []):
            task_id = str(task.get("id") or task.get("task_id") or f"task-{position}")
            conn.execute(
                "INSERT INTO tasks(run_id,task_id,title,status,position,payload_json) VALUES(?,?,?,?,?,?)",
                (run_id, task_id, task.get("title") or task.get("name"), task.get("status"), position, self._json(task)),
            )
        session_ids = run.get("agent_session_ids") or {}
        role_sessions = run.get("role_session_ids") or {}
        if role_sessions:
            for role, value in role_sessions.items():
                if isinstance(value, dict):
                    for agent, session_id in value.items():
                        conn.execute("INSERT INTO agent_sessions(run_id,role,agent,session_id,status,updated_at,payload_json) VALUES(?,?,?,?,?,?,?)", (run_id, str(role), str(agent), session_id, "active", run.get("updated_at"), self._json({"role": role, "agent": agent, "session_id": session_id})))
                else:
                    conn.execute("INSERT INTO agent_sessions(run_id,role,agent,session_id,status,updated_at,payload_json) VALUES(?,?,?,?,?,?,?)", (run_id, str(role), str(run.get("agent") or "qwen"), value, "active", run.get("updated_at"), self._json({"role": role, "session_id": value})))
        else:
            for agent, session_id in session_ids.items():
                conn.execute("INSERT INTO agent_sessions(run_id,role,agent,session_id,status,updated_at,payload_json) VALUES(?,?,?,?,?,?,?)", (run_id, "shared", str(agent), session_id, "active", run.get("updated_at"), self._json({"agent": agent, "session_id": session_id})))
        for event in [*(run.get("timeline") or []), *(run.get("events") or [])]:
            if isinstance(event, dict):
                self._insert_event(conn, run_id, event)
        for position, artifact in enumerate(run.get("artifacts") or []):
            artifact_id = str(artifact.get("id") or artifact.get("path") or artifact.get("name") or f"artifact-{position}")
            conn.execute("INSERT INTO run_artifacts(run_id,artifact_id,path,category,role,visibility,size_bytes,payload_json) VALUES(?,?,?,?,?,?,?,?)", (run_id, artifact_id, artifact.get("path") or artifact.get("name"), artifact.get("category"), artifact.get("role"), artifact.get("visibility"), artifact.get("size") or artifact.get("size_bytes") or 0, self._json(artifact)))
        validations = list(run.get("validation_results") or [])
        for step in run.get("steps") or []:
            config = step.get("config") if isinstance(step.get("config"), dict) else {}
            if step.get("evidence_category") == "validation" or config.get("evidenceCategory") == "validation":
                validations.append({"key": step.get("key"), "status": step.get("status"), "error": step.get("error")})
        for position, result in enumerate(validations):
            key = str(result.get("key") or result.get("name") or f"validation-{position}")
            conn.execute(
                "INSERT OR REPLACE INTO validation_results(run_id,validation_key,status,command,exit_code,payload_json) VALUES(?,?,?,?,?,?)",
                (run_id, key, self._projection_text(result.get("status")), self._projection_text(result.get("command")), result.get("exit_code"), self._json(result)),
            )
        for position, change in enumerate(run.get("file_changes") or []):
            if isinstance(change, str):
                change = {"path": change, "status": "modified"}
            path = str(change.get("path") or change.get("file") or f"change-{position}")
            conn.execute("INSERT OR REPLACE INTO file_changes(run_id,path,change_type,additions,deletions,payload_json) VALUES(?,?,?,?,?,?)", (run_id, path, change.get("status") or change.get("change"), change.get("added") or change.get("additions") or 0, change.get("removed") or change.get("deletions") or 0, self._json(change)))
        for position, checkpoint in enumerate(run.get("checkpoints") or []):
            checkpoint_id = str(checkpoint.get("id") or checkpoint.get("checkpoint_id") or f"checkpoint-{position}")
            conn.execute("INSERT INTO checkpoints(run_id,checkpoint_id,step_key,status,created_at,payload_json) VALUES(?,?,?,?,?,?)", (run_id, checkpoint_id, checkpoint.get("step_key"), checkpoint.get("status"), checkpoint.get("created_at") or checkpoint.get("at"), self._json(checkpoint)))
        lock = run.get("project_lock")
        project_path = run.get("original_project_path") or run.get("project_path")
        if lock and project_path:
            conn.execute("INSERT OR REPLACE INTO project_locks(project_path,run_id,mode,acquired_at,payload_json) VALUES(?,?,?,?,?)", (str(project_path), run_id, lock.get("mode") or "write", lock.get("created_at") or lock.get("acquired_at"), self._json(lock)))

    def _sync_projections(self, conn: sqlite3.Connection, data: dict[str, Any]) -> None:
        for table in (
            "run_events", "run_artifacts", "validation_results", "file_changes", "checkpoints",
            "agent_sessions", "tasks", "run_steps", "runs", "project_locks",
        ):
            conn.execute(f"DELETE FROM {table}")
        for run in data.get("runs", []):
            self._sync_run_projection(conn, run)

    def _sync_changed_projections(self, conn: sqlite3.Connection, before: dict[str, Any], after: dict[str, Any]) -> None:
        before_runs = {str(item.get("id")): item for item in before.get("runs", []) if item.get("id")}
        after_runs = {str(item.get("id")): item for item in after.get("runs", []) if item.get("id")}
        removed = set(before_runs) - set(after_runs)
        for run_id in removed:
            conn.execute("DELETE FROM project_locks WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
        for run_id, run in after_runs.items():
            previous = before_runs.get(run_id)
            if previous is None or self._json(previous) != self._json(run):
                self._sync_run_projection(conn, run)

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
        normalized = self._normalize(data)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (json.dumps(normalized, indent=2, ensure_ascii=False), time.time()),
            )
            self._sync_projections(conn, normalized)
            conn.execute("COMMIT")

    def backup_sync(self, destination: Path | None = None) -> Path:
        destination = destination or self.path.with_name(f"{self.path.stem}.backup-{int(time.time())}{self.path.suffix}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return destination

    def compact_sync(self) -> dict[str, int]:
        """Checkpoint WAL and reclaim free pages during explicit maintenance."""
        before = self.path.stat().st_size if self.path.exists() else 0
        wal_path = Path(f"{self.path}-wal")
        wal_before = wal_path.stat().st_size if wal_path.exists() else 0
        with self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
        after = self.path.stat().st_size if self.path.exists() else 0
        wal_after = wal_path.stat().st_size if wal_path.exists() else 0
        return {
            "database_bytes_before": before,
            "database_bytes_after": after,
            "wal_bytes_before": wal_before,
            "wal_bytes_after": wal_after,
        }

    def projection_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            tables = ("runs", "run_steps", "tasks", "agent_sessions", "run_events", "run_artifacts", "validation_results", "file_changes", "checkpoints", "project_locks")
            return {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}

    @staticmethod
    def _projection_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        """Merge projection columns with the original payload JSON.

        Projection tables intentionally keep only indexed columns. UI/API
        consumers still need the full artifact/step metadata, so ``payload_json``
        is restored here instead of silently dropping fields such as
        ``display_name``, ``media_type`` and ``producer_step_key``.
        """
        columns = dict(row)
        raw = columns.get("payload_json")
        try:
            payload = json.loads(raw) if raw else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        for key, value in columns.items():
            if key == "payload_json":
                continue
            if value is not None or key not in payload:
                payload[key] = value
        return payload

    def query_run_projection(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return None
            run_row = self._projection_payload(run)
            payload = dict(run_row)
            payload["run"] = run_row
            payload["steps"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM run_steps WHERE run_id=? ORDER BY position", (run_id,)).fetchall()]
            payload["tasks"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY position", (run_id,)).fetchall()]
            payload["sessions"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM agent_sessions WHERE run_id=?", (run_id,)).fetchall()]
            payload["events"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM run_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
            payload["validations"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM validation_results WHERE run_id=?", (run_id,)).fetchall()]
            payload["artifacts"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM run_artifacts WHERE run_id=?", (run_id,)).fetchall()]
            payload["file_changes"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM file_changes WHERE run_id=?", (run_id,)).fetchall()]
            payload["checkpoints"] = [self._projection_payload(row) for row in conn.execute("SELECT * FROM checkpoints WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()]
            return payload

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
                before = json.loads(json.dumps(data, ensure_ascii=False))
                result = fn(data)
                data["state_version"] = int(data.get("state_version") or 0) + 1
                conn.execute(
                    "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (json.dumps(data, indent=2, ensure_ascii=False), time.time()),
                )
                self._sync_changed_projections(conn, before, data)
                conn.execute("COMMIT")
                return result
