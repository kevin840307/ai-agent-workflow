from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.command_runner import (
    CommandPolicy,
    CommandPolicyError,
    CommandRequest,
    run_command,
)
from app.core.runtime_context import RuntimeContext, use_runtime_context
from app.persistence.migrations import (
    DatabaseMigrationError,
    DatabaseTooNewError,
    LATEST_SQLITE_SCHEMA_VERSION,
    MIGRATIONS,
    Migration,
    run_migrations,
)
from app.persistence.repositories import store as store_repository
from app.persistence.sqlite_store import SQLiteStore
from app.testing.test_catalog import markers_for_test_file
from scripts.build_release import collect_release_files, validate_release_inputs


class _MemoryStore:
    def __init__(self, value: dict) -> None:
        self.value = value
        self.path = Path("memory.json")

    async def read(self) -> dict:
        return self.value

    async def mutate(self, fn):
        return fn(self.value)


def _context(store) -> RuntimeContext:
    return RuntimeContext(
        store=store,
        bus=SimpleNamespace(),
        run_state=SimpleNamespace(),
        running_tasks={},
        running_processes={},
        agent_manager=SimpleNamespace(),
        workflow_actions=SimpleNamespace(),
        workflow_executor=SimpleNamespace(),
        workflow_kernel=SimpleNamespace(),
    )


def test_fresh_sqlite_applies_ordered_migrations_and_audit_metadata(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"
    store = SQLiteStore(path, default_project_path=lambda: str(tmp_path), default_steps=lambda: [])

    assert store.last_migration["from_version"] == 0
    assert store.last_migration["applied"] == [1, 2, 3, 4]
    assert store.last_migration["backup_path"] is None
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        metadata = conn.execute(
            "SELECT value FROM controller_metadata WHERE key='sqlite_schema_version'"
        ).fetchone()
    assert [row[0] for row in rows] == [1, 2, 3, 4]
    assert all(row[1] and len(row[2]) == 64 for row in rows)
    assert metadata[0] == str(LATEST_SQLITE_SCHEMA_VERSION)


def test_legacy_database_is_backed_up_and_migrated_without_losing_state(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    state = {"state_version": 7, "sessions": [{"id": "s1"}], "messages": [], "runs": [], "workflow_configs": []}
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(1, ?)", (time.time(),))
        conn.execute(
            "CREATE TABLE store_documents (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO store_documents(key, value, updated_at) VALUES('state', ?, ?)",
            (json.dumps(state), time.time()),
        )

    store = SQLiteStore(path, default_project_path=lambda: str(tmp_path), default_steps=lambda: [])

    backup = Path(str(store.last_migration["backup_path"]))
    assert backup.is_file() and backup.stat().st_size > 0
    assert store.last_migration["applied"] == [2, 3, 4]
    assert store.load_sync()["sessions"][0]["id"] == "s1"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 4
        assert "event_key" in {row[1] for row in conn.execute("PRAGMA table_info(run_events)")}


def test_newer_database_is_rejected_instead_of_downgraded(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(99, ?)", (time.time(),))

    with pytest.raises(DatabaseTooNewError, match="DATABASE_SCHEMA_TOO_NEW"):
        SQLiteStore(path, default_project_path=lambda: str(tmp_path), default_steps=lambda: [])


def test_failed_migration_rolls_back_schema_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "rollback.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        for version in (1, 2, 3):
            conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)", (version, time.time()))
        conn.execute("CREATE TABLE store_documents (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)")

    def fail(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE should_rollback(id INTEGER)")
        raise RuntimeError("boom")

    import app.persistence.migrations as migrations

    monkeypatch.setattr(migrations, "MIGRATIONS", (*MIGRATIONS[:3], Migration(4, "forced-failure", fail)))
    with sqlite3.connect(path, isolation_level=None) as conn:
        with pytest.raises(DatabaseMigrationError, match="DATABASE_MIGRATION_FAILED"):
            run_migrations(conn, path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    assert "should_rollback" not in tables
    assert 4 not in versions


def test_runtime_context_can_be_overridden_without_patching_module_globals() -> None:
    async def scenario() -> None:
        first = _context(_MemoryStore({"source": "first"}))
        second = _context(_MemoryStore({"source": "second"}))

        with use_runtime_context(first):
            assert (await store_repository.read())["source"] == "first"
            with use_runtime_context(second):
                assert (await store_repository.read())["source"] == "second"
            assert (await store_repository.read())["source"] == "first"

    asyncio.run(scenario())


def test_project_command_runner_redacts_and_truncates_output(tmp_path: Path) -> None:
    script = "print('OPENAI_API_KEY=super-secret-value'); print('x' * 5000)"
    result = run_command(
        CommandRequest(
            command=[sys.executable, "-c", script],
            cwd=tmp_path,
            project_root=tmp_path,
            policy=CommandPolicy.PROJECT,
            timeout_seconds=10,
            max_output_chars=500,
        )
    )
    assert result.ok
    assert "super-secret-value" not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert result.output_truncated is True


def test_command_runner_timeout_terminates_process(tmp_path: Path) -> None:
    result = run_command(
        CommandRequest(
            command=[sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            project_root=tmp_path,
            policy=CommandPolicy.PROJECT,
            timeout_seconds=0.2,
        )
    )
    assert result.timed_out is True
    assert result.returncode == 124
    assert result.failure_code == "TIMEOUT"


def test_agent_generated_commands_require_argv_and_forbid_shell(tmp_path: Path) -> None:
    with pytest.raises(CommandPolicyError, match="REQUIRES_ARGV"):
        run_command(
            CommandRequest(
                command="echo unsafe",
                cwd=tmp_path,
                project_root=tmp_path,
                policy=CommandPolicy.AGENT_GENERATED,
            )
        )
    with pytest.raises(CommandPolicyError, match="FORBIDS_SHELL"):
        run_command(
            CommandRequest(
                command=[sys.executable, "-c", "print('x')"],
                cwd=tmp_path,
                project_root=tmp_path,
                policy=CommandPolicy.AGENT_GENERATED,
                shell=True,
            )
        )


def test_project_command_cannot_escape_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    with pytest.raises(CommandPolicyError, match="OUTSIDE_PROJECT"):
        run_command(
            CommandRequest(
                command=[sys.executable, "-c", "print('x')"],
                cwd=outside,
                project_root=project,
                policy=CommandPolicy.PROJECT,
            )
        )


def test_test_catalog_separates_manual_real_agent_and_fast_tiers() -> None:
    assert markers_for_test_file("tests/test_api_smoke.py") == {"unit"}
    assert markers_for_test_file("tests/test_v24_stability_convergence.py") == {"contract"}
    assert markers_for_test_file("tests/test_workflow_resilience_e2e.py") == {"e2e"}
    assert markers_for_test_file("tests/test_real_qwen_unattended_manual.py") == {"manual", "real_agent"}


def test_runtime_facade_imports_are_bounded() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    matches = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from app.runtime_modules import api as runtime" in text:
            matches.append(path.relative_to(root).as_posix())
    assert len(matches) <= 15, matches


def test_release_allowlist_keeps_required_command_templates_and_contract_schema() -> None:
    assert validate_release_inputs() == []
    paths = {item.archive_path.as_posix() for item in collect_release_files()}
    assert {
        "data/ai-workflow/WORKFLOW_CONTRACT_SCHEMA.md",
        "data/agent-commands/qwen/commands/wf.md",
        "data/agent-commands/qwen/commands/wstep.md",
        "data/agent-commands/opencode/commands/wf.md",
        "data/agent-commands/opencode/commands/wstep.md",
    }.issubset(paths)
