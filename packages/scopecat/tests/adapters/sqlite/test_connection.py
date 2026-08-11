from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest

from scopecat.adapters.sqlite.connection import (
    SQLiteDatabase,
    connect,
    immediate_transaction,
)


def test_connect_applies_shared_sqlite_policy(tmp_path: Path) -> None:
    with closing(
        connect(tmp_path / "project.sqlite3", busy_timeout_seconds=0.125)
    ) as connection:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 125


def test_immediate_transaction_commits_or_rolls_back(tmp_path: Path) -> None:
    database = tmp_path / "project.sqlite3"
    with immediate_transaction(database) as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
        connection.execute("INSERT INTO values_table VALUES ('committed')")

    with (
        pytest.raises(RuntimeError, match="abort"),
        immediate_transaction(database) as connection,
    ):
        connection.execute("INSERT INTO values_table VALUES ('rolled-back')")
        raise RuntimeError("abort")

    with closing(connect(database)) as connection:
        rows = connection.execute("SELECT value FROM values_table").fetchall()

    assert [row["value"] for row in rows] == ["committed"]


def test_concurrent_writers_both_commit(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "project.sqlite3")
    with database.write_transaction() as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")

    first_entered = Event()
    release_first = Event()
    second_started = Event()

    def hold_first_writer() -> None:
        with database.write_transaction() as connection:
            connection.execute("INSERT INTO values_table VALUES ('first')")
            first_entered.set()
            assert release_first.wait(timeout=5)

    def enter_second_writer() -> None:
        second_started.set()
        with database.write_transaction() as connection:
            connection.execute("INSERT INTO values_table VALUES ('second')")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_first_writer)
        assert first_entered.wait(timeout=5)
        second = executor.submit(enter_second_writer)
        assert second_started.wait(timeout=5)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    with closing(database.connect()) as connection:
        rows = connection.execute(
            "SELECT value FROM values_table ORDER BY value"
        ).fetchall()
    assert [row["value"] for row in rows] == ["first", "second"]


def test_read_snapshot_does_not_reserve_the_writer(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "project.sqlite3")
    with closing(database.connect()) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
    with database.write_transaction() as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")

    with database.read_transaction() as reader:
        assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 0
        with database.write_transaction() as writer:
            writer.execute("INSERT INTO values_table VALUES ('committed')")
        assert reader.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 0

    with closing(database.connect()) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 1
        )
