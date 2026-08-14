"""Shared SQLite connection and transaction policy."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import RLock

DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0


class SQLiteBusyError(RuntimeError):
    """The project database writer is temporarily owned elsewhere."""


class SQLiteDatabase:
    """Coordinate every connection to one daemon-owned SQLite database."""

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_seconds: float = DEFAULT_BUSY_TIMEOUT_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.busy_timeout_seconds = busy_timeout_seconds
        self._writer_lock = RLock()

    def connect(self) -> sqlite3.Connection:
        return connect(
            self.path,
            busy_timeout_seconds=self.busy_timeout_seconds,
        )

    @contextmanager
    def read_transaction(self) -> Generator[sqlite3.Connection]:
        """Open a consistent snapshot without reserving the writer slot."""

        with closing(self.connect()) as connection:
            connection.execute("BEGIN")
            try:
                yield connection
            finally:
                connection.rollback()

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Connection]:
        """Serialize the project's single SQLite writer inside the daemon."""

        if not self._writer_lock.acquire(timeout=self.busy_timeout_seconds):
            raise SQLiteBusyError("project database writer is busy")
        try:
            with immediate_transaction(
                self.path,
                busy_timeout_seconds=self.busy_timeout_seconds,
            ) as connection:
                yield connection
        except sqlite3.OperationalError as error:
            primary_code = error.sqlite_errorcode & 0xFF
            if primary_code not in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }:
                raise
            raise SQLiteBusyError("project database writer is busy") from error
        finally:
            self._writer_lock.release()


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
    connection.execute("PRAGMA synchronous = NORMAL")
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
    "SQLiteBusyError",
    "SQLiteDatabase",
    "connect",
    "immediate_transaction",
]
