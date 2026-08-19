"""Physical SQLite project-store ownership and bootstrap."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.object_store import ImmutableObjectStore
from scopecat_server.storage.sqlite.schema import (
    PROJECT_SCHEMA_SQL,
    PROJECT_SCHEMA_VERSION,
)


class ProjectStoreError(RuntimeError):
    """The SQLite project store could not be opened or initialized."""


class SchemaVersionError(ProjectStoreError):
    """The database belongs to an unsupported project-store schema."""


class SQLiteProjectStore:
    """Own the one database and object directory used by a project."""

    def __init__(
        self,
        database: SQLiteDatabase,
        objects: str | Path,
    ) -> None:
        self.sqlite = database
        self.database = database.path
        self.objects = ImmutableObjectStore(objects)

    def bootstrap(self) -> None:
        """Create the current store, refusing implicit schema migration."""

        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self.objects.bootstrap()
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                if _has_project_schema(connection):
                    self._require_current_version(connection)
                elif _has_application_tables(connection):
                    raise SchemaVersionError(
                        "project store predates the current schema boundary; "
                        "rebuild it explicitly"
                    )
                else:
                    connection.executescript(PROJECT_SCHEMA_SQL)
                    self._require_current_version(connection)
        except SchemaVersionError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise ProjectStoreError("failed to bootstrap project store") from error

    def schema_version(self) -> int:
        """Return the supported project-store version or reject the database."""

        try:
            with self.sqlite.read_connection() as connection:
                return self._require_current_version(connection)
        except SchemaVersionError:
            raise
        except sqlite3.Error as error:
            raise ProjectStoreError("failed to inspect project store") from error

    def close(self) -> None:
        """Checkpoint and close the shared SQLite database."""

        self.sqlite.close()

    def _require_current_version(self, connection: sqlite3.Connection) -> int:
        row = _one(
            connection.execute("SELECT version FROM project_schema WHERE singleton = 1")
        )
        version = None if row is None else cast("int", row["version"])
        if version != PROJECT_SCHEMA_VERSION:
            raise SchemaVersionError(
                "unsupported project-store schema version: "
                f"{version}; expected {PROJECT_SCHEMA_VERSION}; rebuild it explicitly"
            )
        return version

    def _connect(self) -> sqlite3.Connection:
        return self.sqlite.connect()


def _has_project_schema(connection: sqlite3.Connection) -> bool:
    row = _one(
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'project_schema'
            """
        )
    )
    return row is not None


def _has_application_tables(connection: sqlite3.Connection) -> bool:
    row = _one(
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            LIMIT 1
            """
        )
    )
    return row is not None


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


__all__ = [
    "ProjectStoreError",
    "SQLiteProjectStore",
    "SchemaVersionError",
]
