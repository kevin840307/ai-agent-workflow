from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

LATEST_SQLITE_SCHEMA_VERSION = 4


class DatabaseMigrationError(RuntimeError):
    """Raised when the controller database cannot be migrated safely."""


class DatabaseTooNewError(DatabaseMigrationError):
    """Raised when an older controller opens a database created by a newer release."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]

    @property
    def checksum(self) -> str:
        value = f"{self.version}:{self.name}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _index_exists(conn: sqlite3.Connection, index: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    ).fetchone() is not None


def _migration_1_document_store(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS store_documents "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
    )


def _migration_2_projection_tables(conn: sqlite3.Connection) -> None:
    statements: Iterable[str] = (
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
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
        "CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_path, created_at)",
        """
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
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_steps_status ON run_steps(run_id, status)",
        """
        CREATE TABLE IF NOT EXISTS tasks (
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            title TEXT,
            status TEXT,
            position INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(run_id, task_id),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        )
        """,
        """
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            step_key TEXT,
            event_type TEXT,
            message TEXT,
            occurred_at TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, id)",
        """
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
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS validation_results (
            run_id TEXT NOT NULL,
            validation_key TEXT NOT NULL,
            status TEXT,
            command TEXT,
            exit_code INTEGER,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(run_id, validation_key),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS file_changes (
            run_id TEXT NOT NULL,
            path TEXT NOT NULL,
            change_type TEXT,
            additions INTEGER,
            deletions INTEGER,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(run_id, path),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            run_id TEXT NOT NULL,
            checkpoint_id TEXT NOT NULL,
            step_key TEXT,
            status TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(run_id, checkpoint_id),
            FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS project_locks (
            project_path TEXT PRIMARY KEY,
            run_id TEXT,
            mode TEXT,
            acquired_at TEXT,
            payload_json TEXT NOT NULL
        )
        """,
    )
    for statement in statements:
        conn.execute(statement)


def _migration_3_event_idempotency(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "run_events"):
        _migration_2_projection_tables(conn)
    if "event_key" not in _column_names(conn, "run_events"):
        conn.execute("ALTER TABLE run_events ADD COLUMN event_key TEXT")
    if not _index_exists(conn, "idx_events_key"):
        conn.execute("CREATE UNIQUE INDEX idx_events_key ON run_events(run_id, event_key)")


def _migration_4_migration_audit(conn: sqlite3.Connection) -> None:
    columns = _column_names(conn, "schema_migrations")
    if "name" not in columns:
        conn.execute("ALTER TABLE schema_migrations ADD COLUMN name TEXT")
    if "checksum" not in columns:
        conn.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
    if "execution_ms" not in columns:
        conn.execute("ALTER TABLE schema_migrations ADD COLUMN execution_ms REAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS controller_metadata "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO controller_metadata(key, value, updated_at) VALUES('sqlite_schema_version', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(LATEST_SQLITE_SCHEMA_VERSION), time.time()),
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "document-store", _migration_1_document_store),
    Migration(2, "normalized-run-projections", _migration_2_projection_tables),
    Migration(3, "event-idempotency-key", _migration_3_event_idempotency),
    Migration(4, "migration-audit-metadata", _migration_4_migration_audit),
)


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    _ensure_migration_table(conn)
    return {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def current_version(conn: sqlite3.Connection) -> int:
    versions = applied_versions(conn)
    return max(versions, default=0)


def _database_has_user_state(conn: sqlite3.Connection) -> bool:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    return bool(tables - {"schema_migrations"})


def create_pre_migration_backup(path: Path, *, from_version: int, to_version: int) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    destination = path.with_name(
        f"{path.stem}.pre-migration-v{from_version}-to-v{to_version}-{timestamp}{path.suffix or '.sqlite3'}"
    )
    with sqlite3.connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    return destination


def run_migrations(conn: sqlite3.Connection, path: Path) -> dict[str, object]:
    """Apply all missing migrations in order, one transaction per version.

    Existing databases are backed up once before the first schema change. Every
    migration is idempotent, but an applied migration is never silently rerun.
    A database containing a version newer than this controller is rejected.
    """

    _ensure_migration_table(conn)
    versions = applied_versions(conn)
    future = sorted(version for version in versions if version > LATEST_SQLITE_SCHEMA_VERSION)
    if future:
        raise DatabaseTooNewError(
            "DATABASE_SCHEMA_TOO_NEW: database version "
            f"{future[-1]} is newer than supported version {LATEST_SQLITE_SCHEMA_VERSION}"
        )

    missing = [migration for migration in MIGRATIONS if migration.version not in versions]
    backup_path: Path | None = None
    auto_backup = os.environ.get("AIWF_SQLITE_AUTO_BACKUP", "1").strip().lower() not in {"0", "false", "no", "off"}
    if missing and auto_backup and path.exists() and path.stat().st_size > 0 and _database_has_user_state(conn):
        backup_path = create_pre_migration_backup(
            path,
            from_version=max(versions, default=0),
            to_version=LATEST_SQLITE_SCHEMA_VERSION,
        )

    applied: list[int] = []
    for migration in missing:
        started = time.monotonic()
        try:
            conn.execute("BEGIN IMMEDIATE")
            migration.apply(conn)
            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            columns = _column_names(conn, "schema_migrations")
            if {"name", "checksum", "execution_ms"}.issubset(columns):
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, name, checksum, execution_ms) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (migration.version, time.time(), migration.name, migration.checksum, elapsed_ms),
                )
            else:
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (migration.version, time.time()),
                )
            conn.execute("COMMIT")
            applied.append(migration.version)
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise DatabaseMigrationError(
                f"DATABASE_MIGRATION_FAILED: v{migration.version} {migration.name}: {exc}"
            ) from exc

    # V4 adds audit columns after V1-V3 may already have been inserted. Backfill
    # deterministic metadata without changing the original applied timestamps.
    columns = _column_names(conn, "schema_migrations")
    if {"name", "checksum"}.issubset(columns):
        for migration in MIGRATIONS:
            conn.execute(
                "UPDATE schema_migrations SET name=COALESCE(name, ?), checksum=COALESCE(checksum, ?) WHERE version=?",
                (migration.name, migration.checksum, migration.version),
            )

    return {
        "schema": "aiwf.sqlite-migration.v1",
        "from_version": max(versions, default=0),
        "to_version": LATEST_SQLITE_SCHEMA_VERSION,
        "applied": applied,
        "backup_path": str(backup_path) if backup_path else None,
    }


def verify_schema(conn: sqlite3.Connection) -> None:
    required_tables = {
        "schema_migrations",
        "store_documents",
        "runs",
        "run_steps",
        "tasks",
        "agent_sessions",
        "run_events",
        "run_artifacts",
        "validation_results",
        "file_changes",
        "checkpoints",
        "project_locks",
        "controller_metadata",
    }
    actual = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    missing = sorted(required_tables - actual)
    if missing:
        raise DatabaseMigrationError(f"DATABASE_SCHEMA_INCOMPLETE: missing tables: {', '.join(missing)}")
    if "event_key" not in _column_names(conn, "run_events") or not _index_exists(conn, "idx_events_key"):
        raise DatabaseMigrationError("DATABASE_SCHEMA_INCOMPLETE: run_events idempotency schema is missing")
    version = current_version(conn)
    if version != LATEST_SQLITE_SCHEMA_VERSION:
        raise DatabaseMigrationError(
            f"DATABASE_SCHEMA_VERSION_MISMATCH: expected {LATEST_SQLITE_SCHEMA_VERSION}, found {version}"
        )


__all__ = [
    "DatabaseMigrationError",
    "DatabaseTooNewError",
    "LATEST_SQLITE_SCHEMA_VERSION",
    "MIGRATIONS",
    "applied_versions",
    "create_pre_migration_backup",
    "current_version",
    "run_migrations",
    "verify_schema",
]
