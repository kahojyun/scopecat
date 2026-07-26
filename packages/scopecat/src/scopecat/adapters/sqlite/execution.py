"""SQLite execution persistence backed by the shared run object store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from scopecat.adapters.sqlite.connection import immediate_transaction
from scopecat.adapters.sqlite.object_store import ObjectStoreError, StoredObject
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository
from scopecat.measurements.datasets import (
    MEASUREMENT_DATASET_KIND,
    RAW_MEASUREMENTS_DATASET_ID,
)
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.runs.refs import (
    EXECUTION_JOURNAL_DIR,
    dataset_content_ref,
)
from scopecat.sdk.journal import ExecutionJournalError


class ExecutionJournalConflict(ExecutionJournalError):
    """A write disagrees with already committed execution state."""


@dataclass(frozen=True, slots=True)
class PreparedExecutionRecord[TModel: BaseModel]:
    """Immutable object-store write prepared before a SQLite transaction."""

    durable: TModel
    ref: str
    stored: StoredObject


class SQLiteExecutionJournal:
    """Append transitions with a transactionally assigned per-run sequence."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        try:
            with _transaction(self._runs) as connection:
                committed, _created = self.append_in_transaction(connection, entry)
                return committed
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit execution journal entry: {error}"
            ) from error

    def append_in_transaction(
        self,
        connection: sqlite3.Connection,
        entry: ExecutionTransition,
    ) -> tuple[ExecutionTransition, bool]:
        """Append through an existing transaction without owning its boundary."""

        if entry.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "execution journal entry run_id does not match its journal"
            )
        content_hash = execution_transition_content_hash(entry)
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT digest FROM execution_journal_entries
                    WHERE run_id = ? AND content_hash = ?
                    """,
                    (self._run_id, content_hash),
                )
            )
            if existing is not None:
                return (
                    _read_stored_model(
                        self._runs,
                        _text(existing, "digest"),
                        ExecutionTransition,
                    ),
                    False,
                )
            row = _one(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(sequence), -1) + 1 AS sequence
                    FROM execution_journal_entries
                    WHERE run_id = ?
                    """,
                    (self._run_id,),
                )
            )
            assert row is not None  # noqa: S101
            committed = self._commit_transition(
                connection,
                entry,
                sequence=_integer(row, "sequence"),
                content_hash=content_hash,
            )
            return committed, True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit execution journal entry: {error}"
            ) from error

    def _commit_transition(
        self,
        connection: sqlite3.Connection,
        entry: ExecutionTransition,
        *,
        sequence: int,
        content_hash: str,
    ) -> ExecutionTransition:
        committed = ExecutionTransition.model_validate(
            {
                **entry.model_dump(mode="python"),
                "sequence": sequence,
                "timestamp": datetime.now(tz=UTC),
            }
        )
        ref = f"{EXECUTION_JOURNAL_DIR}/{sequence:08d}.json"
        stored = _store_model(self._runs, committed)
        _publish_ref(connection, self._run_id, ref, stored)
        connection.execute(
            """
            INSERT INTO execution_journal_entries(
                run_id, sequence, content_hash, digest
            )
            VALUES (?, ?, ?, ?)
            """,
            (self._run_id, sequence, content_hash, stored.digest),
        )
        return committed


class SQLiteMeasurementDatasetRepository:
    """Append and seal canonical measurement ranges with database CAS."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        prepared = self.prepare_append(append)
        try:
            with _transaction(self._runs) as connection:
                receipt, _created = self.append_prepared_in_transaction(
                    connection,
                    prepared,
                )
                return receipt
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to append measurement dataset: {error}"
            ) from error

    def prepare_append(
        self,
        append: MeasurementDatasetAppend,
    ) -> PreparedExecutionRecord[MeasurementDatasetAppend]:
        """Publish immutable append content before entering the write transaction."""

        durable = MeasurementDatasetAppend.model_validate(
            append.model_dump(mode="python")
        )
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = f"{_dataset_ref()}/chunks/{durable.start_index:020d}.json"
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def append_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[MeasurementDatasetAppend],
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish prepared append metadata in an existing transaction."""

        durable = prepared.durable
        ref = prepared.ref
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT operation_id, content_hash, ref
                    FROM execution_measurement_appends
                    WHERE run_id = ? AND start_index = ?
                    """,
                    (self._run_id, durable.start_index),
                )
            )
            if existing is not None:
                if (
                    _text(existing, "operation_id") != durable.operation_id
                    or _text(existing, "content_hash") != durable.content_hash
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset append already has different content"
                    )
                return (
                    MeasurementDatasetReceipt(
                        operation_id=_text(existing, "operation_id"),
                        dataset_content_hash=_text(existing, "content_hash"),
                        dataset_ref=_text(existing, "ref"),
                    ),
                    False,
                )
            if _dataset_sealed(connection, self._run_id):
                raise ExecutionJournalConflict("measurement dataset is already sealed")
            previous = _measurement_rows(
                connection,
                self._run_id,
            )
            if durable.start_index != sum(
                _integer(row, "record_count") for row in previous
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset append is not the next contiguous range"
                )
            if any(
                _text(row, "contract_fingerprint")
                != durable.recording_contract_fingerprint
                for row in previous
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset append changed its contract"
                )
            _publish_ref(connection, self._run_id, ref, prepared.stored)
            connection.execute(
                """
                INSERT INTO execution_measurement_appends(
                    run_id, start_index, operation_id,
                    content_hash, contract_fingerprint, record_count,
                    ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.start_index,
                    durable.operation_id,
                    durable.content_hash,
                    durable.recording_contract_fingerprint,
                    len(durable.records),
                    ref,
                ),
            )
            return _append_receipt(durable, ref), True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to append measurement dataset: {error}"
            ) from error

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        prepared = self.prepare_seal(seal)
        try:
            with _transaction(self._runs) as connection:
                receipt, _created = self.seal_prepared_in_transaction(
                    connection,
                    prepared,
                )
                return receipt
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to seal measurement dataset: {error}"
            ) from error

    def prepare_seal(
        self,
        seal: MeasurementDatasetSeal,
    ) -> MeasurementDatasetSeal:
        """Validate seal content before entering the write transaction."""

        durable = MeasurementDatasetSeal.model_validate(seal.model_dump(mode="python"))
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        return durable

    def seal_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: MeasurementDatasetSeal,
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish prepared seal metadata in an existing transaction."""

        durable = prepared
        try:

            def commit_prepared() -> tuple[MeasurementDatasetReceipt, bool]:
                existing = _one(
                    connection.execute(
                        """
                        SELECT
                            operation_id,
                            content_hash,
                            dataset_content_hash
                        FROM execution_measurement_seals
                        WHERE run_id = ?
                        """,
                        (self._run_id,),
                    )
                )
                if existing is not None:
                    if (
                        _text(existing, "operation_id") != durable.operation_id
                        or _text(existing, "content_hash") != durable.content_hash
                    ):
                        raise ExecutionJournalConflict(
                            "measurement dataset seal already has different content"
                        )
                    return (
                        MeasurementDatasetReceipt(
                            operation_id=_text(existing, "operation_id"),
                            dataset_content_hash=_text(
                                existing,
                                "dataset_content_hash",
                            ),
                            dataset_ref=_dataset_ref(),
                        ),
                        False,
                    )
                appends = _measurement_rows(
                    connection,
                    self._run_id,
                )
                if sum(_integer(row, "record_count") for row in appends) != (
                    durable.point_count
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal point count is incomplete"
                    )
                if any(
                    _text(row, "contract_fingerprint")
                    != durable.recording_contract_fingerprint
                    for row in appends
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal changed its contract"
                    )
                actual_hash = measurement_dataset_content_hash(
                    recording_contract_fingerprint=(
                        durable.recording_contract_fingerprint
                    ),
                    append_content_hashes=tuple(
                        _text(row, "content_hash") for row in appends
                    ),
                )
                if actual_hash != durable.dataset_content_hash:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal content hash does not match appends"
                    )
                connection.execute(
                    """
                    INSERT INTO execution_measurement_seals(
                        run_id, operation_id, content_hash,
                        dataset_content_hash
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        self._run_id,
                        durable.operation_id,
                        durable.content_hash,
                        durable.dataset_content_hash,
                    ),
                )
                return _seal_receipt(durable), True

            return commit_prepared()
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to seal measurement dataset: {error}"
            ) from error

    def measurements(
        self,
    ) -> tuple[MeasurementRecord, ...]:
        try:
            return tuple(
                self._runs.read_measurement_records(
                    self._run_id,
                    _dataset_ref(),
                )
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset: {error}"
            ) from error


def _dataset_ref() -> str:
    return dataset_content_ref(
        dataset_id=RAW_MEASUREMENTS_DATASET_ID,
        kind=MEASUREMENT_DATASET_KIND,
    )


def _append_receipt(
    append: MeasurementDatasetAppend,
    ref: str,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=append.operation_id,
        dataset_content_hash=append.content_hash,
        dataset_ref=ref,
    )


def _seal_receipt(
    seal: MeasurementDatasetSeal,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=seal.operation_id,
        dataset_content_hash=seal.dataset_content_hash,
        dataset_ref=_dataset_ref(),
    )


def _dataset_sealed(
    connection: sqlite3.Connection,
    run_id: str,
) -> bool:
    return (
        _one(
            connection.execute(
                """
                SELECT 1 AS sealed FROM execution_measurement_seals
                WHERE run_id = ?
                """,
                (run_id,),
            )
        )
        is not None
    )


def _measurement_rows(
    connection: sqlite3.Connection,
    run_id: str,
) -> list[sqlite3.Row]:
    return _all(
        connection.execute(
            """
            SELECT * FROM execution_measurement_appends
            WHERE run_id = ?
            ORDER BY start_index
            """,
            (run_id,),
        )
    )


def _store_model(runs: SQLiteRunRepository, model: BaseModel) -> StoredObject:
    try:
        content = (
            json.dumps(
                model.model_dump(mode="json"),
                allow_nan=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        return runs.objects.put(content)
    except (
        ObjectStoreError,
        PydanticSerializationError,
        TypeError,
        ValueError,
    ) as error:
        raise ExecutionJournalError(
            f"execution record is not durably serializable: {error}"
        ) from error


def _read_stored_model[TModel: BaseModel](
    runs: SQLiteRunRepository,
    digest: str,
    model_type: type[TModel],
) -> TModel:
    return model_type.model_validate_json(runs.objects.read(digest))


def _publish_ref(
    connection: sqlite3.Connection,
    run_id: str,
    ref: str,
    stored: StoredObject,
) -> None:
    connection.execute(
        """
        INSERT INTO run_repository_refs(run_id, ref, digest)
        VALUES (?, ?, ?)
        ON CONFLICT(run_id, ref) DO UPDATE SET
            digest = excluded.digest
        """,
        (run_id, ref, stored.digest),
    )


@contextmanager
def _transaction(
    runs: SQLiteRunRepository,
) -> Generator[sqlite3.Connection]:
    with immediate_transaction(
        runs.database,
        busy_timeout_seconds=runs.busy_timeout_seconds,
    ) as connection:
        yield connection


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])
