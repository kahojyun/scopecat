"""Shared SQLite connection and transaction policy."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path

DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0


def connect(
    database: str | Path,
    *,
    busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
) -> sqlite3.Connection:
    """Open a connection with the project-wide SQLite policy."""

    connection = sqlite3.connect(
        database,
        isolation_level=None,
        timeout=busy_timeout_seconds,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    busy_timeout_ms = round(busy_timeout_seconds * 1000)
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return connection


@contextmanager
def immediate_transaction(
    database: str | Path,
    *,
    busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
) -> Generator[sqlite3.Connection]:
    """Own one immediate transaction using the shared connection policy."""

    with closing(
        connect(database, busy_timeout_seconds=busy_timeout_seconds)
    ) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


__all__ = [
    "DEFAULT_BUSY_TIMEOUT_SECONDS",
    "connect",
    "immediate_transaction",
]
