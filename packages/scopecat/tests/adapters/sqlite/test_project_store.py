from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scopecat.adapters.sqlite import SchemaVersionError, SQLiteProjectStore


def test_bootstrap_creates_the_complete_project_store_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "control.sqlite3"
    store = SQLiteProjectStore(database, tmp_path / "objects")

    store.bootstrap()
    store.bootstrap()

    assert store.schema_version() == 1
    with sqlite3.connect(database) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert journal_mode == ("wal",)
    assert {
        "project_schema",
        "runs",
        "durable_events",
        "run_repository_refs",
        "config_registry_entries",
        "execution_journal_entries",
    } <= tables


def test_bootstrap_refuses_an_unknown_project_schema(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    store = SQLiteProjectStore(database, tmp_path / "objects")
    store.bootstrap()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE project_schema SET version = 99")

    with pytest.raises(SchemaVersionError, match="version: 99"):
        store.bootstrap()


def test_bootstrap_refuses_tables_without_a_project_schema(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE old_state (value TEXT)")

    store = SQLiteProjectStore(database, tmp_path / "objects")
    with pytest.raises(SchemaVersionError, match="rebuild it explicitly"):
        store.bootstrap()
