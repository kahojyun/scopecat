"""SQLite persistence for the daemon-owned configuration registry."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import TracebackType
from typing import Self, cast

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.adapters.sqlite.config_schema import (
    CONFIG_REGISTRY_SCHEMA_SQL,
    CONFIG_REGISTRY_SCHEMA_VERSION,
)
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.kernel.errors import (
    Conflict,
    DataIntegrityError,
    StorageError,
)
from scopecat.kernel.problems import (
    ModelLocation,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.runs.repository import RunRepository

CONFIG_REGISTRY_ROOT = "config-registry"
CONFIG_REGISTRY_ACTIVE_REF = f"{CONFIG_REGISTRY_ROOT}/active.json"


class SQLiteConfigRegistryRepository:
    """Registry view bound to one workspace transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def active_ref(self) -> str:
        return CONFIG_REGISTRY_ACTIVE_REF

    def entry_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/entries/{entry_id}.json"

    def config_ref(self, entry_id: str) -> str:
        return f"{CONFIG_REGISTRY_ROOT}/configs/{entry_id}.config-profile-snapshot.json"

    def entry_exists(self, entry_id: str) -> bool:
        try:
            row = _one(
                self._connection.execute(
                    """
                    SELECT 1 AS present
                    FROM config_registry_entries
                    WHERE entry_id = ?
                    """,
                    (entry_id,),
                )
            )
        except sqlite3.Error as error:
            raise _storage_failure(self.entry_ref(entry_id)) from error
        return row is not None

    def list_entries(self) -> tuple[ConfigRegistryEntry, ...]:
        try:
            rows = _all(
                self._connection.execute(
                    """
                    SELECT entry_id, entry_json
                    FROM config_registry_entries
                    ORDER BY registered_at, entry_id
                    """
                )
            )
        except sqlite3.Error as error:
            raise _storage_failure(CONFIG_REGISTRY_ROOT) from error
        return tuple(
            _parse_model(
                _text(row, "entry_json"),
                ConfigRegistryEntry,
                ref=self.entry_ref(_text(row, "entry_id")),
                code="config_registry.record_invalid",
            )
            for row in rows
        )

    def read_entry(self, entry_id: str) -> ConfigRegistryEntry:
        ref = self.entry_ref(entry_id)
        try:
            row = _one(
                self._connection.execute(
                    """
                    SELECT entry_json
                    FROM config_registry_entries
                    WHERE entry_id = ?
                    """,
                    (entry_id,),
                )
            )
        except sqlite3.Error as error:
            raise _storage_failure(ref) from error
        if row is None:
            raise _missing_record(ref)
        return _parse_model(
            _text(row, "entry_json"),
            ConfigRegistryEntry,
            ref=ref,
            code="config_registry.record_invalid",
        )

    def read_config(self, ref: str) -> ConfigProfileSnapshot:
        try:
            row = _one(
                self._connection.execute(
                    """
                    SELECT config_json
                    FROM config_registry_entries
                    WHERE config_ref = ?
                    """,
                    (ref,),
                )
            )
        except sqlite3.Error as error:
            raise _storage_failure(ref) from error
        if row is None:
            raise _missing_record(ref)
        return _parse_model(
            _text(row, "config_json"),
            ConfigProfileSnapshot,
            ref=ref,
            code="config_registry.config_invalid",
        )

    def read_active_state(self) -> ConfigRegistryActiveState | None:
        try:
            selector = _one(
                self._connection.execute(
                    """
                    SELECT generation, active_entry_id
                    FROM config_registry_active
                    WHERE singleton = 1
                    """
                )
            )
            rows = _all(
                self._connection.execute(
                    """
                    SELECT generation, record_json
                    FROM config_registry_activations
                    ORDER BY generation
                    """
                )
            )
        except sqlite3.Error as error:
            raise _storage_failure(self.active_ref) from error
        if selector is None:
            return None
        history = tuple(
            _parse_model(
                _text(row, "record_json"),
                ConfigRegistryActivationRecord,
                ref=f"{self.active_ref}#generation-{_integer(row, 'generation')}",
                code="config_registry.activation_record_invalid",
            )
            for row in rows
        )
        if not history:
            raise _integrity_failure(
                self.active_ref,
                code="config_registry.active_state_invalid",
                message="config registry active selector has no activation history",
            )
        latest = history[-1]
        return _validate_model(
            {
                "generation": _integer(selector, "generation"),
                "active_entry_id": _text(selector, "active_entry_id"),
                "active_entry_content_hash": latest.entry_content_hash,
                "history": history,
                "updated_at": latest.recorded_at,
            },
            ConfigRegistryActiveState,
            ref=self.active_ref,
            code="config_registry.active_state_invalid",
        )

    def commit_registration(
        self,
        *,
        entry: ConfigRegistryEntry,
        config: ConfigProfileSnapshot,
    ) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO config_registry_entries(
                    entry_id,
                    config_ref,
                    entry_json,
                    config_json,
                    registered_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO NOTHING
                """,
                (
                    entry.id,
                    entry.config_ref,
                    _encode_model(entry, ref=self.entry_ref(entry.id)),
                    _encode_model(config, ref=entry.config_ref),
                    entry.registered_at.isoformat(),
                ),
            )
        except sqlite3.Error as error:
            raise _storage_failure(self.entry_ref(entry.id)) from error

    def commit_activation(
        self,
        *,
        expected_generation: int,
        record: ConfigRegistryActivationRecord,
    ) -> None:
        try:
            current_generation = _current_generation(self._connection)
            if current_generation != expected_generation:
                raise _generation_conflict(
                    expected=expected_generation,
                    actual=current_generation,
                )
            if record.generation != expected_generation + 1:
                raise _generation_conflict(
                    expected=expected_generation,
                    actual=record.generation - 1,
                )
            self._connection.execute(
                """
                INSERT INTO config_registry_activations(
                    generation,
                    record_id,
                    entry_id,
                    record_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.generation,
                    record.id,
                    record.entry_id,
                    _encode_model(record, ref=self.active_ref),
                ),
            )
            if expected_generation == 0:
                self._connection.execute(
                    """
                    INSERT INTO config_registry_active(
                        singleton,
                        generation,
                        active_entry_id
                    )
                    VALUES (1, ?, ?)
                    """,
                    (
                        record.generation,
                        record.entry_id,
                    ),
                )
                return
            cursor = self._connection.execute(
                """
                UPDATE config_registry_active
                SET generation = ?,
                    active_entry_id = ?
                WHERE singleton = 1 AND generation = ?
                """,
                (
                    record.generation,
                    record.entry_id,
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise _generation_conflict(
                    expected=expected_generation,
                    actual=_current_generation(self._connection),
                )
        except (Conflict, DataIntegrityError):
            raise
        except sqlite3.Error as error:
            raise _storage_failure(self.active_ref) from error


class SQLiteWorkspaceUnitOfWork:
    """One immediate transaction for registry state and injected run reads."""

    def __init__(
        self,
        database: str | Path,
        *,
        runs: RunRepository,
        busy_timeout_seconds: float = 5,
    ) -> None:
        self.database = Path(database)
        self.runs = runs
        self._busy_timeout_seconds = busy_timeout_seconds
        self._connection: sqlite3.Connection | None = None
        self._registry: SQLiteConfigRegistryRepository | None = None

    @property
    def registry(self) -> SQLiteConfigRegistryRepository:
        if self._registry is None:
            msg = "workspace unit of work has not been entered"
            raise RuntimeError(msg)
        return self._registry

    def __enter__(self) -> Self:
        if self._connection is not None:
            msg = "workspace unit of work cannot be entered twice"
            raise RuntimeError(msg)
        connection = _connect(
            self.database,
            busy_timeout_seconds=self._busy_timeout_seconds,
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as error:
            connection.close()
            raise _storage_failure(CONFIG_REGISTRY_ROOT) from error
        self._connection = connection
        self._registry = SQLiteConfigRegistryRepository(connection)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        connection = self._connection
        if connection is None:
            msg = "workspace unit of work was not entered"
            raise RuntimeError(msg)
        self._connection = None
        self._registry = None
        try:
            if exc_type is None:
                connection.commit()
            else:
                connection.rollback()
        except sqlite3.Error as error:
            raise _storage_failure(CONFIG_REGISTRY_ROOT) from error
        finally:
            connection.close()


class SQLiteConfigRegistryStore:
    """Factory for registry transactions sharing a workspace database."""

    def __init__(
        self,
        database: str | Path,
        *,
        runs: RunRepository,
        busy_timeout_seconds: float = 5,
    ) -> None:
        self.database = Path(database)
        self.runs = runs
        self._busy_timeout_seconds = busy_timeout_seconds

    def bootstrap(self) -> None:
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            with closing(
                _connect(
                    self.database,
                    busy_timeout_seconds=self._busy_timeout_seconds,
                )
            ) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(CONFIG_REGISTRY_SCHEMA_SQL)
                row = _one(
                    connection.execute(
                        """
                        SELECT version
                        FROM config_registry_schema
                        WHERE singleton = 1
                        """
                    )
                )
        except (OSError, sqlite3.Error) as error:
            raise _storage_failure(CONFIG_REGISTRY_ROOT) from error
        version = None if row is None else _integer(row, "version")
        if version != CONFIG_REGISTRY_SCHEMA_VERSION:
            raise _schema_failure(version)

    def unit_of_work(self) -> SQLiteWorkspaceUnitOfWork:
        return SQLiteWorkspaceUnitOfWork(
            self.database,
            runs=self.runs,
            busy_timeout_seconds=self._busy_timeout_seconds,
        )


def _connect(
    database: Path,
    *,
    busy_timeout_seconds: float,
) -> sqlite3.Connection:
    connection = sqlite3.connect(
        database,
        isolation_level=None,
        timeout=busy_timeout_seconds,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _parse_model[TModel: BaseModel](
    content: str,
    model_type: type[TModel],
    *,
    ref: str,
    code: str,
) -> TModel:
    try:
        return model_type.model_validate_json(content)
    except ValidationError as error:
        raise _integrity_failure(
            ref,
            code=code,
            message="config registry record does not match its durable schema",
        ) from error


def _validate_model[TModel: BaseModel](
    value: object,
    model_type: type[TModel],
    *,
    ref: str,
    code: str,
) -> TModel:
    try:
        return model_type.model_validate(value)
    except ValidationError as error:
        raise _integrity_failure(
            ref,
            code=code,
            message="config registry record does not match its durable schema",
        ) from error


def _encode_model(model: BaseModel, *, ref: str) -> str:
    try:
        return model.model_dump_json()
    except (PydanticSerializationError, TypeError, ValueError) as error:
        raise _integrity_failure(
            ref,
            code="config_registry.record_not_serializable",
            message="config registry record cannot be represented durably",
        ) from error


def _current_generation(connection: sqlite3.Connection) -> int:
    row = _one(
        connection.execute(
            """
            SELECT generation
            FROM config_registry_active
            WHERE singleton = 1
            """
        )
    )
    return 0 if row is None else _integer(row, "generation")


def _generation_conflict(*, expected: int, actual: int) -> Conflict:
    return Conflict(
        [
            blocking_problem(
                "config_registry.conflict",
                "config registry active state changed",
                category=ProblemCategory.CONFLICT,
                phase=ProblemPhase.CONFIGURATION,
                location=ModelLocation(
                    root="config_registry",
                    path=("expected_generation",),
                ),
                related_locations=(StorageLocation(ref=CONFIG_REGISTRY_ACTIVE_REF),),
                details={
                    "expected_generation": expected,
                    "actual_generation": actual,
                },
            )
        ]
    )


def _missing_record(ref: str) -> DataIntegrityError:
    return _integrity_failure(
        ref,
        code="config_registry.record_missing",
        message="config registry is missing a referenced durable record",
    )


def _schema_failure(version: int | None) -> DataIntegrityError:
    return _integrity_failure(
        CONFIG_REGISTRY_ROOT,
        code="storage.schema_unsupported",
        message=f"unsupported config registry schema version: {version}",
    )


def _integrity_failure(
    ref: str,
    *,
    code: str,
    message: str,
) -> DataIntegrityError:
    return DataIntegrityError(
        [
            blocking_problem(
                code,
                message,
                category=ProblemCategory.DATA_INTEGRITY,
                phase=ProblemPhase.CONFIGURATION,
                location=StorageLocation(ref=ref),
            )
        ]
    )


def _storage_failure(ref: str) -> StorageError:
    return StorageError(
        [
            blocking_problem(
                "config_registry.storage_failed",
                "storage could not complete the config registry operation",
                category=ProblemCategory.STORAGE,
                phase=ProblemPhase.CONFIGURATION,
                location=StorageLocation(ref=ref),
            )
        ]
    )


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> tuple[sqlite3.Row, ...]:
    return cast("tuple[sqlite3.Row, ...]", tuple(cursor.fetchall()))


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])


__all__ = [
    "SQLiteConfigRegistryRepository",
    "SQLiteConfigRegistryStore",
    "SQLiteWorkspaceUnitOfWork",
]
