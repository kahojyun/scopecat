from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from threading import Event, Thread

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


def test_database_serializes_in_process_writers(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "project.sqlite3", busy_timeout_seconds=0.2)
    with database.write_transaction() as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")

    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def hold_first_writer() -> None:
        with database.write_transaction() as connection:
            connection.execute("INSERT INTO values_table VALUES ('first')")
            first_entered.set()
            assert release_first.wait(timeout=1)

    def enter_second_writer() -> None:
        assert first_entered.wait(timeout=1)
        with database.write_transaction() as connection:
            second_entered.set()
            connection.execute("INSERT INTO values_table VALUES ('second')")

    first = Thread(target=hold_first_writer)
    second = Thread(target=enter_second_writer)
    first.start()
    second.start()
    assert first_entered.wait(timeout=1)
    assert not second_entered.wait(timeout=0.05)
    release_first.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
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
