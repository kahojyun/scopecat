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

    assert store.schema_version() == 11
    with sqlite3.connect(database) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        columns = {
            table: {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for table in (
                "scheduler_runs",
                "durable_events",
                "run_repository_refs",
                "execution_measurement_appends",
                "execution_measurement_seals",
            )
        }
    assert journal_mode == ("wal",)
    assert {
        "project_schema",
        "scheduler_runs",
        "durable_events",
        "run_repository_refs",
        "config_registry_entries",
        "config_registry_activations",
    } <= tables
    assert "config_registry_active" not in tables
    assert "admitted_at" not in columns["scheduler_runs"]
    assert "size" not in columns["run_repository_refs"]
    assert "dataset_id" not in columns["execution_measurement_appends"]
    assert "digest" not in columns["execution_measurement_appends"]
    assert {"run_sequence", "deduplication_key"} <= columns["durable_events"]
    assert {
        "contract_fingerprint",
        "dataset_id",
        "digest",
        "point_count",
        "ref",
    }.isdisjoint(columns["execution_measurement_seals"])


@pytest.mark.parametrize("version", (8, 99))
def test_bootstrap_refuses_a_noncurrent_project_schema(
    tmp_path: Path,
    version: int,
) -> None:
    database = tmp_path / "control.sqlite3"
    store = SQLiteProjectStore(database, tmp_path / "objects")
    store.bootstrap()
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE project_schema SET version = ?", (version,))

    with pytest.raises(SchemaVersionError, match=f"version: {version}"):
        store.bootstrap()


def test_bootstrap_refuses_tables_without_a_project_schema(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE old_state (value TEXT)")

    store = SQLiteProjectStore(database, tmp_path / "objects")
    with pytest.raises(SchemaVersionError, match="rebuild it explicitly"):
        store.bootstrap()
