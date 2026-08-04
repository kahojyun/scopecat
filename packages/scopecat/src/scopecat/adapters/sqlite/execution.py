"""SQLite execution persistence backed by the shared project store."""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from scopecat.adapters.sqlite.connection import connect
from scopecat.adapters.sqlite.object_store import ObjectStoreError, StoredObject
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
)
from scopecat.records.measurement import MeasurementDatasetSchema, MeasurementRecord
from scopecat.records.measurement_recording import (
    CANONICAL_MEASUREMENT_DATASET_REF,
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
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
    """Append effect transitions to the canonical durable-event stream."""

    _EVENT_KIND = "execution_transition_committed"

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

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
                    SELECT run_sequence, payload_json, occurred_at
                    FROM durable_events
                    WHERE run_id = ? AND kind = ? AND deduplication_key = ?
                    """,
                    (self._run_id, self._EVENT_KIND, content_hash),
                )
            )
            if existing is not None:
                return (
                    _execution_transition(self._run_id, existing),
                    False,
                )
            row = _one(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(run_sequence), -1) + 1 AS sequence
                    FROM durable_events
                    WHERE run_id = ? AND kind = ?
                    """,
                    (self._run_id, self._EVENT_KIND),
                )
            )
            assert row is not None
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
        payload = committed.model_dump(
            mode="json",
            exclude={"run_id", "timestamp"},
        )
        connection.execute(
            """
            INSERT INTO durable_events(
                run_id,
                kind,
                payload_json,
                occurred_at,
                run_sequence,
                deduplication_key
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._run_id,
                self._EVENT_KIND,
                json.dumps(
                    payload,
                    allow_nan=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                committed.timestamp.isoformat(timespec="microseconds"),
                sequence,
                content_hash,
            ),
        )
        return committed


class SQLiteMeasurementDatasetRepository:
    """Append and seal canonical measurement ranges with database CAS."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def prepare_header(
        self,
        header: MeasurementDatasetHeader,
    ) -> PreparedExecutionRecord[MeasurementDatasetHeader]:
        """Publish the immutable dataset contract before entering a transaction."""

        durable = header.model_copy(deep=True)
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = f"{CANONICAL_MEASUREMENT_DATASET_REF}/header.json"
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def header_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[MeasurementDatasetHeader],
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish one canonical header or replay its exact durable value."""

        durable = prepared.durable
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT operation_id, content_hash
                    FROM execution_measurement_headers
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
                        "measurement dataset header already has different content"
                    )
                return _header_receipt(durable), False
            if _measurement_rows(connection, self._run_id) or _dataset_sealed(
                connection, self._run_id
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset content exists without its header"
                )
            _publish_ref(connection, self._run_id, prepared.ref, prepared.stored)
            connection.execute(
                """
                INSERT INTO execution_measurement_headers(
                    run_id, operation_id, content_hash,
                    contract_fingerprint, expected_record_count, ref
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.operation_id,
                    durable.content_hash,
                    durable.recording_contract_fingerprint,
                    durable.expected_record_count,
                    prepared.ref,
                ),
            )
            return _header_receipt(durable), True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to initialize measurement dataset: {error}"
            ) from error

    def prepare_append(
        self,
        append: MeasurementDatasetAppend,
    ) -> PreparedExecutionRecord[MeasurementDatasetAppend]:
        """Publish immutable append content before entering the write transaction."""

        durable = append.model_copy(deep=True)
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = (
            f"{CANONICAL_MEASUREMENT_DATASET_REF}/chunks/"
            f"{durable.start_index:020d}.json"
        )
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
                    ),
                    False,
                )
            if _dataset_sealed(connection, self._run_id):
                raise ExecutionJournalConflict("measurement dataset is already sealed")
            header = _measurement_header_row(connection, self._run_id)
            if header is None:
                raise ExecutionJournalConflict(
                    "measurement dataset append requires a header"
                )
            if _text(header, "content_hash") != durable.header_content_hash:
                raise ExecutionJournalConflict(
                    "measurement dataset append references a different header"
                )
            record_count = _measurement_record_count(connection, self._run_id)
            if durable.start_index != record_count:
                raise ExecutionJournalConflict(
                    "measurement dataset append is not the next contiguous range"
                )
            if record_count + len(durable.records) > _integer(
                header, "expected_record_count"
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset append exceeds its declared point count"
                )
            _publish_ref(connection, self._run_id, ref, prepared.stored)
            connection.execute(
                """
                INSERT INTO execution_measurement_appends(
                    run_id, start_index, operation_id,
                    content_hash, header_content_hash, record_count,
                    ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.start_index,
                    durable.operation_id,
                    durable.content_hash,
                    durable.header_content_hash,
                    len(durable.records),
                    ref,
                ),
            )
            return _append_receipt(durable), True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to append measurement dataset: {error}"
            ) from error

    def prepare_seal(
        self,
        seal: MeasurementDatasetSeal,
    ) -> MeasurementDatasetSeal:
        """Validate seal content before entering the write transaction."""

        durable = seal
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
                        ),
                        False,
                    )
                header = _measurement_header_row(connection, self._run_id)
                if header is None:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal requires a header"
                    )
                if _text(header, "content_hash") != durable.header_content_hash:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal references a different header"
                    )
                if durable.point_count > _integer(header, "expected_record_count"):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal exceeds its declared point count"
                    )
                appends = _measurement_rows(connection, self._run_id)
                if sum(_integer(row, "record_count") for row in appends) != (
                    durable.point_count
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal point count is incomplete"
                    )
                actual_hash = measurement_dataset_content_hash(
                    header_content_hash=durable.header_content_hash,
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
                    CANONICAL_MEASUREMENT_DATASET_REF,
                )
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset: {error}"
            ) from error

    def measurement_schema(self) -> MeasurementDatasetSchema | None:
        """Read the canonical schema without loading any measurement append."""

        try:
            with closing(
                connect(
                    self._runs.database,
                    busy_timeout_seconds=self._runs.busy_timeout_seconds,
                )
            ) as connection:
                header_row = _measurement_header_row(connection, self._run_id)
            if header_row is None:
                return None
            return self._runs.read_model(
                self._run_id,
                _text(header_row, "ref"),
                MeasurementDatasetHeader,
            ).dataset_schema
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset schema: {error}"
            ) from error

    def measurement_page(
        self,
        *,
        limit: int,
        offset: int,
        include_schema: bool = True,
    ) -> tuple[
        tuple[MeasurementRecord, ...],
        int | None,
        MeasurementDatasetSchema | None,
    ]:
        """Read one record page plus its canonical dataset schema."""

        try:
            with closing(
                connect(
                    self._runs.database,
                    busy_timeout_seconds=self._runs.busy_timeout_seconds,
                )
            ) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT start_index, record_count, ref
                        FROM execution_measurement_appends
                        WHERE run_id = ?
                          AND start_index < ?
                          AND start_index + record_count > ?
                        ORDER BY start_index
                        """,
                        (self._run_id, offset + limit, offset),
                    )
                )
                header_row = (
                    _measurement_header_row(connection, self._run_id)
                    if include_schema
                    else None
                )
                total = _measurement_record_count(connection, self._run_id)

            if include_schema and header_row is None:
                return (), None, None

            dataset_schema = (
                None
                if header_row is None
                else self._runs.read_model(
                    self._run_id,
                    _text(header_row, "ref"),
                    MeasurementDatasetHeader,
                ).dataset_schema
            )
            appends: dict[str, MeasurementDatasetAppend] = {}
            for row in rows:
                ref = _text(row, "ref")
                appends[ref] = self._runs.read_model(
                    self._run_id,
                    ref,
                    MeasurementDatasetAppend,
                )
            page_end = offset + limit
            items: list[MeasurementRecord] = []
            for row in rows:
                start_index = _integer(row, "start_index")
                chunk = appends[_text(row, "ref")]
                chunk_start = max(0, offset - start_index)
                chunk_end = min(
                    _integer(row, "record_count"),
                    page_end - start_index,
                )
                items.extend(chunk.records[chunk_start:chunk_end])
            next_offset = offset + len(items) if offset + len(items) < total else None
            return tuple(items), next_offset, dataset_schema
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset page: {error}"
            ) from error

    def measurement_records_at(
        self,
        point_indices: tuple[int, ...],
    ) -> tuple[MeasurementRecord, ...]:
        """Read selected durable point indices without materializing other chunks."""

        selected = tuple(sorted(set(point_indices)))
        try:
            with closing(
                connect(
                    self._runs.database,
                    busy_timeout_seconds=self._runs.busy_timeout_seconds,
                )
            ) as connection:
                rows = _measurement_rows(connection, self._run_id)
            records_by_index: dict[int, MeasurementRecord] = {}
            for row in rows:
                start = _integer(row, "start_index")
                end = start + _integer(row, "record_count")
                first = bisect_left(selected, start)
                last = bisect_left(selected, end)
                if first == last:
                    continue
                chunk = self._runs.read_model(
                    self._run_id,
                    _text(row, "ref"),
                    MeasurementDatasetAppend,
                )
                for point_index in selected[first:last]:
                    records_by_index[point_index] = chunk.records[point_index - start]
            return tuple(
                records_by_index[point_index]
                for point_index in point_indices
                if point_index in records_by_index
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read selected measurement records: {error}"
            ) from error


def _header_receipt(
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=header.operation_id,
        dataset_content_hash=header.content_hash,
    )


def _append_receipt(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=append.operation_id,
        dataset_content_hash=append.content_hash,
    )


def _seal_receipt(
    seal: MeasurementDatasetSeal,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=seal.operation_id,
        dataset_content_hash=seal.dataset_content_hash,
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


def _measurement_header_row(
    connection: sqlite3.Connection,
    run_id: str,
) -> sqlite3.Row | None:
    return _one(
        connection.execute(
            """
            SELECT * FROM execution_measurement_headers
            WHERE run_id = ?
            """,
            (run_id,),
        )
    )


def _measurement_record_count(
    connection: sqlite3.Connection,
    run_id: str,
) -> int:
    row = _one(
        connection.execute(
            """
            SELECT COALESCE(SUM(record_count), 0) AS record_count
            FROM execution_measurement_appends
            WHERE run_id = ?
            """,
            (run_id,),
        )
    )
    assert row is not None
    return _integer(row, "record_count")


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


def _execution_transition(
    run_id: str,
    row: sqlite3.Row,
) -> ExecutionTransition:
    payload = cast(
        "dict[str, object]",
        json.loads(_text(row, "payload_json")),
    )
    return ExecutionTransition.model_validate(
        {
            **payload,
            "run_id": run_id,
            "sequence": _integer(row, "run_sequence"),
            "timestamp": _text(row, "occurred_at"),
        }
    )


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


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])
