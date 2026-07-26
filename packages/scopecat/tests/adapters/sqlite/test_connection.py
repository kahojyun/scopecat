from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scopecat.adapters.sqlite.connection import connect, immediate_transaction


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
