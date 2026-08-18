from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.project_store import (
    SchemaVersionError,
    SQLiteProjectStore,
)


def test_bootstrap_creates_the_complete_project_store_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.sqlite3"
    store = SQLiteProjectStore(SQLiteDatabase(database), tmp_path / "objects")

    store.bootstrap()
    store.bootstrap()

    store.schema_version()
    with sqlite3.connect(database) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        instrument_session_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(instrument_sessions)")
        }
        scheduler_run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(scheduler_runs)")
        }
        analysis_publication_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(analysis_publications)")
        }
    assert journal_mode == ("wal",)
    assert {
        "project_schema",
        "scheduler_runs",
        "durable_events",
        "runs",
        "run_outcomes",
        "run_contents",
        "run_repository_refs",
        "analysis_publications",
        "project_analysis_contents",
        "project_analysis_repository_refs",
        "procedure_runs",
        "procedure_step_attempts",
        "procedure_leases",
        "config_registry_entries",
        "config_registry_activations",
        "config_operations",
    } <= tables
    assert {"renewed_at", "expires_at"} <= instrument_session_columns
    assert "cancellation_requested_at" in scheduler_run_columns
    assert "record_entry_json" in analysis_publication_columns
    assert "published_at" in analysis_publication_columns
    assert "manifest_json" not in analysis_publication_columns


@pytest.mark.parametrize("version", (0, 99))
def test_bootstrap_refuses_a_noncurrent_project_schema(
    tmp_path: Path,
    version: int,
) -> None:
    database = tmp_path / "control.sqlite3"
    store = SQLiteProjectStore(SQLiteDatabase(database), tmp_path / "objects")
    store.bootstrap()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE project_schema SET version = ?", (version,))

    with pytest.raises(SchemaVersionError, match=f"version: {version}"):
        store.bootstrap()


def test_bootstrap_refuses_tables_without_a_project_schema(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE old_state (value TEXT)")

    store = SQLiteProjectStore(SQLiteDatabase(database), tmp_path / "objects")
    with pytest.raises(SchemaVersionError, match="rebuild it explicitly"):
        store.bootstrap()
