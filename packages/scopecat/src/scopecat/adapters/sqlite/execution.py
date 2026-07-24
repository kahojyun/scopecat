"""SQLite execution persistence backed by the shared run object store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from pydantic_core import PydanticSerializationError

from scopecat.adapters.sqlite.execution_schema import (
    EXECUTION_SCHEMA_SQL,
    EXECUTION_SCHEMA_VERSION,
)
from scopecat.adapters.sqlite.object_store import ObjectStoreError, StoredObject
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository
from scopecat.execution.ports.journal import ExecutionJournalError
from scopecat.measurements.datasets import MEASUREMENT_DATASET_KIND
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.runs.refs import (
    EXECUTION_JOURNAL_DIR,
    EXECUTION_PAYLOADS_DIR,
    EXECUTION_READBACKS_DIR,
    dataset_content_ref,
)


class ExecutionJournalConflict(ExecutionJournalError):
    """A write disagrees with already committed execution state."""


@dataclass(frozen=True, slots=True)
class ExecutionTransitionBatchCommit:
    """Committed transitions and whether this call created the batch."""

    transitions: tuple[ExecutionTransition, ...]
    created: bool


@dataclass(frozen=True, slots=True)
class PreparedExecutionRecord[TModel: BaseModel]:
    """Immutable object-store write prepared before a SQLite transaction."""

    durable: TModel
    ref: str
    stored: StoredObject


def bootstrap_execution_schema(runs: SQLiteRunRepository) -> None:
    """Create execution indexes in an already bootstrapped run database."""

    try:
        with closing(_connect(runs)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(EXECUTION_SCHEMA_SQL)
            row = _one(
                connection.execute(
                    """
                    SELECT version FROM execution_repository_schema
                    WHERE singleton = 1
                    """
                )
            )
    except sqlite3.Error as error:
        raise ExecutionJournalError(
            f"failed to bootstrap execution repository: {error}"
        ) from error
    version = None if row is None else _integer(row, "version")
    if version != EXECUTION_SCHEMA_VERSION:
        raise ExecutionJournalError(
            f"unsupported execution repository schema version: {version}"
        )


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
        try:
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
            )
            return committed, True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit execution journal entry: {error}"
            ) from error

    def append_batch(
        self,
        batch_id: str,
        entries: tuple[ExecutionTransition, ...],
    ) -> ExecutionTransitionBatchCommit:
        """Atomically append or replay one transport batch."""

        try:
            with _transaction(self._runs) as connection:
                return self.append_batch_in_transaction(
                    connection,
                    batch_id,
                    entries,
                )
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit execution journal batch: {error}"
            ) from error

    def append_batch_in_transaction(
        self,
        connection: sqlite3.Connection,
        batch_id: str,
        entries: tuple[ExecutionTransition, ...],
    ) -> ExecutionTransitionBatchCommit:
        """Append or replay a transport batch in an existing transaction."""

        if not batch_id or not entries:
            raise ValueError("execution transition batch must be non-empty")
        if any(entry.run_id != self._run_id for entry in entries):
            raise ExecutionJournalConflict(
                "execution journal batch run_id does not match its journal"
            )
        content_hash = _batch_content_hash(entries)
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT * FROM execution_journal_batches
                    WHERE run_id = ? AND batch_id = ?
                    """,
                    (self._run_id, batch_id),
                )
            )
            if existing is not None:
                if _text(existing, "content_hash") != content_hash:
                    raise ExecutionJournalConflict(
                        "execution transition batch id has different content"
                    )
                first_sequence = _integer(existing, "first_sequence")
                transition_count = _integer(existing, "transition_count")
                committed = tuple(
                    _read_stored_model(
                        self._runs,
                        _text(row, "digest"),
                        ExecutionTransition,
                    )
                    for row in _batch_rows(
                        connection,
                        self._run_id,
                        first_sequence,
                        transition_count,
                    )
                )
                return ExecutionTransitionBatchCommit(
                    transitions=committed,
                    created=False,
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
            first_sequence = _integer(row, "sequence")
            committed = tuple(
                self._commit_transition(
                    connection,
                    entry,
                    sequence=first_sequence + index,
                )
                for index, entry in enumerate(entries)
            )
            connection.execute(
                """
                INSERT INTO execution_journal_batches(
                    run_id, batch_id, content_hash,
                    first_sequence, transition_count
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    batch_id,
                    content_hash,
                    first_sequence,
                    len(committed),
                ),
            )
            return ExecutionTransitionBatchCommit(
                transitions=committed,
                created=True,
            )
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit execution journal batch: {error}"
            ) from error

    def _commit_transition(
        self,
        connection: sqlite3.Connection,
        entry: ExecutionTransition,
        *,
        sequence: int,
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
                run_id, sequence, ref, digest
            )
            VALUES (?, ?, ?, ?)
            """,
            (self._run_id, sequence, ref, stored.digest),
        )
        return committed

    def entries(self) -> tuple[ExecutionTransition, ...]:
        try:
            with closing(_connect(self._runs)) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT ref FROM execution_journal_entries
                        WHERE run_id = ?
                        ORDER BY sequence
                        """,
                        (self._run_id,),
                    )
                )
            return tuple(
                self._runs.read_model(
                    self._run_id,
                    _text(row, "ref"),
                    ExecutionTransition,
                )
                for row in rows
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read execution journal: {error}"
            ) from error


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

    def append_in_transaction(
        self,
        connection: sqlite3.Connection,
        append: MeasurementDatasetAppend,
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Append a measurement range in an existing transaction."""

        return self.append_prepared_in_transaction(
            connection,
            self.prepare_append(append),
        )

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
        ref = (
            f"{_dataset_ref(durable.dataset_id)}/chunks/{durable.start_index:020d}.json"
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
                    WHERE run_id = ? AND dataset_id = ? AND start_index = ?
                    """,
                    (self._run_id, durable.dataset_id, durable.start_index),
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
            if _dataset_sealed(connection, self._run_id, durable.dataset_id):
                raise ExecutionJournalConflict("measurement dataset is already sealed")
            previous = _measurement_rows(
                connection,
                self._run_id,
                durable.dataset_id,
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
                    run_id, dataset_id, start_index, operation_id,
                    content_hash, contract_fingerprint, record_count,
                    ref, digest
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.dataset_id,
                    durable.start_index,
                    durable.operation_id,
                    durable.content_hash,
                    durable.recording_contract_fingerprint,
                    len(durable.records),
                    ref,
                    prepared.stored.digest,
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

    def seal_in_transaction(
        self,
        connection: sqlite3.Connection,
        seal: MeasurementDatasetSeal,
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Seal a measurement dataset in an existing transaction."""

        return self.seal_prepared_in_transaction(
            connection,
            self.prepare_seal(seal),
        )

    def prepare_seal(
        self,
        seal: MeasurementDatasetSeal,
    ) -> PreparedExecutionRecord[MeasurementDatasetSeal]:
        """Publish immutable seal content before entering the write transaction."""

        durable = MeasurementDatasetSeal.model_validate(seal.model_dump(mode="python"))
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = f"{_dataset_ref(durable.dataset_id)}/seal.json"
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def seal_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[MeasurementDatasetSeal],
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish prepared seal metadata in an existing transaction."""

        durable = prepared.durable
        ref = prepared.ref
        try:

            def commit_prepared() -> tuple[MeasurementDatasetReceipt, bool]:
                existing = _one(
                    connection.execute(
                        """
                        SELECT
                            operation_id,
                            content_hash,
                            dataset_content_hash,
                            ref
                        FROM execution_measurement_seals
                        WHERE run_id = ? AND dataset_id = ?
                        """,
                        (self._run_id, durable.dataset_id),
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
                            dataset_ref=_text(existing, "ref"),
                        ),
                        False,
                    )
                appends = _measurement_rows(
                    connection,
                    self._run_id,
                    durable.dataset_id,
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
                _publish_ref(connection, self._run_id, ref, prepared.stored)
                connection.execute(
                    """
                    INSERT INTO execution_measurement_seals(
                        run_id, dataset_id, operation_id, content_hash,
                        dataset_content_hash, contract_fingerprint, point_count,
                        ref, digest
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._run_id,
                        durable.dataset_id,
                        durable.operation_id,
                        durable.content_hash,
                        durable.dataset_content_hash,
                        durable.recording_contract_fingerprint,
                        durable.point_count,
                        ref,
                        prepared.stored.digest,
                    ),
                )
                return _seal_receipt(durable, ref), True

            return commit_prepared()
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to seal measurement dataset: {error}"
            ) from error

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        try:
            with closing(_connect(self._runs)) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT ref FROM execution_measurement_appends
                        WHERE run_id = ?
                        ORDER BY dataset_id, start_index
                        """,
                        (self._run_id,),
                    )
                )
            return tuple(
                MeasurementRecord.model_validate(record.model_dump(mode="python"))
                for row in rows
                for record in self._runs.read_model(
                    self._run_id,
                    _text(row, "ref"),
                    MeasurementDatasetAppend,
                ).records
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset: {error}"
            ) from error

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]:
        try:
            with closing(_connect(self._runs)) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT
                            operation_id,
                            start_index,
                            record_count,
                            contract_fingerprint,
                            content_hash
                        FROM execution_measurement_appends
                        WHERE run_id = ?
                        ORDER BY dataset_id, start_index
                        """,
                        (self._run_id,),
                    )
                )
            return tuple(
                MeasurementDatasetAppendIndex(
                    operation_id=_text(row, "operation_id"),
                    start_index=_integer(row, "start_index"),
                    record_count=_integer(row, "record_count"),
                    recording_contract_fingerprint=_text(
                        row,
                        "contract_fingerprint",
                    ),
                    append_content_hash=_text(row, "content_hash"),
                )
                for row in rows
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement append indices: {error}"
            ) from error


class SQLiteCollectionRecordRepository:
    """Commit idempotent collection readbacks and resolve exact receipts."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        prepared = self.prepare_commit(chunk)
        try:
            with _transaction(self._runs) as connection:
                receipt, _created = self.commit_prepared_in_transaction(
                    connection,
                    prepared,
                )
                return receipt
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit collection readback: {error}"
            ) from error

    def commit_in_transaction(
        self,
        connection: sqlite3.Connection,
        chunk: CollectionChunk,
    ) -> tuple[CollectionChunkReceipt, bool]:
        """Commit a collection readback in an existing transaction."""

        return self.commit_prepared_in_transaction(
            connection,
            self.prepare_commit(chunk),
        )

    def prepare_commit(
        self,
        chunk: CollectionChunk,
    ) -> PreparedExecutionRecord[CollectionChunk]:
        """Publish immutable readback content before entering the write transaction."""

        if chunk.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "collection chunk run_id does not match its repository"
            )
        durable = CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        ref = _operation_ref(EXECUTION_READBACKS_DIR, durable.operation_id)
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def commit_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[CollectionChunk],
    ) -> tuple[CollectionChunkReceipt, bool]:
        """Publish prepared readback metadata in an existing transaction."""

        durable = prepared.durable
        ref = prepared.ref
        try:

            def commit_prepared() -> tuple[CollectionChunkReceipt, bool]:
                existing = _one(
                    connection.execute(
                        """
                        SELECT content_hash, ref, digest
                        FROM execution_collections
                        WHERE run_id = ? AND operation_id = ?
                        """,
                        (self._run_id, durable.operation_id),
                    )
                )
                if existing is not None:
                    if (
                        _text(existing, "content_hash") != durable.content_hash
                        or _text(existing, "digest") != prepared.stored.digest
                    ):
                        raise ExecutionJournalConflict(
                            "collection operation already has a different readback"
                        )
                    return _collection_receipt(durable, _text(existing, "ref")), False
                _publish_ref(connection, self._run_id, ref, prepared.stored)
                connection.execute(
                    """
                    INSERT INTO execution_collections(
                        run_id, operation_id, content_hash, ref, digest
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._run_id,
                        durable.operation_id,
                        durable.content_hash,
                        ref,
                        prepared.stored.digest,
                    ),
                )
                return _collection_receipt(durable, ref), True

            return commit_prepared()
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit collection readback: {error}"
            ) from error

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        try:
            with closing(_connect(self._runs)) as connection:
                return self.resolve_in_transaction(connection, receipt)
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to resolve collection readback: {error}"
            ) from error

    def resolve_in_transaction(
        self,
        connection: sqlite3.Connection,
        receipt: CollectionChunkReceipt,
    ) -> CollectionChunk:
        """Resolve a collection receipt through an existing connection."""

        durable = CollectionChunkReceipt.model_validate(receipt.model_dump(mode="json"))
        expected_ref = _operation_ref(
            EXECUTION_READBACKS_DIR,
            durable.operation_id,
        )
        if durable.ref != expected_ref:
            raise ExecutionJournalConflict(
                "collection receipt ref does not match its operation"
            )
        try:
            row = _one(
                connection.execute(
                    """
                    SELECT content_hash, ref, digest FROM execution_collections
                    WHERE run_id = ? AND operation_id = ?
                    """,
                    (self._run_id, durable.operation_id),
                )
            )
            if (
                row is None
                or _text(row, "ref") != durable.ref
                or _text(row, "content_hash") != durable.content_hash
            ):
                raise ExecutionJournalConflict(
                    "collection receipt is not backed by this repository"
                )
            chunk = _read_stored_model(
                self._runs,
                _text(row, "digest"),
                CollectionChunk,
            )
            if (
                chunk.operation_id != durable.operation_id
                or chunk.content_hash != durable.content_hash
            ):
                raise ExecutionJournalError(
                    "collection receipt does not resolve to its committed chunk"
                )
            return CollectionChunk.model_validate(chunk.model_dump(mode="json"))
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to resolve collection readback: {error}"
            ) from error

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        try:
            with closing(_connect(self._runs)) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT operation_id, ref, content_hash
                        FROM execution_collections
                        WHERE run_id = ?
                        ORDER BY operation_id
                        """,
                        (self._run_id,),
                    )
                )
            return tuple(
                CollectionChunkReceipt(
                    operation_id=_text(row, "operation_id"),
                    ref=_text(row, "ref"),
                    content_hash=_text(row, "content_hash"),
                )
                for row in rows
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to list collection receipts: {error}"
            ) from error


class SQLitePayloadEvidenceCommitter:
    """Commit one exact structural payload record per operation."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence:
        prepared = self.prepare_commit(evidence)
        try:
            with _transaction(self._runs) as connection:
                committed, _created = self.commit_prepared_in_transaction(
                    connection,
                    prepared,
                )
                return committed
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit payload evidence: {error}"
            ) from error

    def commit_in_transaction(
        self,
        connection: sqlite3.Connection,
        evidence: PayloadEvidence,
    ) -> tuple[CommittedPayloadEvidence, bool]:
        """Commit payload evidence in an existing transaction."""

        return self.commit_prepared_in_transaction(
            connection,
            self.prepare_commit(evidence),
        )

    def prepare_commit(
        self,
        evidence: PayloadEvidence,
    ) -> PreparedExecutionRecord[PayloadEvidence]:
        """Publish immutable evidence content before entering the write transaction."""

        if evidence.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "payload evidence run_id does not match its committer"
            )
        durable = PayloadEvidence.model_validate(evidence.model_dump(mode="json"))
        ref = _operation_ref(EXECUTION_PAYLOADS_DIR, durable.operation_id)
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def commit_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[PayloadEvidence],
    ) -> tuple[CommittedPayloadEvidence, bool]:
        """Publish prepared evidence metadata in an existing transaction."""

        durable = prepared.durable
        ref = prepared.ref
        try:

            def commit_prepared() -> tuple[CommittedPayloadEvidence, bool]:
                existing = _one(
                    connection.execute(
                        """
                        SELECT content_hash, ref, digest
                        FROM execution_payload_evidence
                        WHERE run_id = ? AND operation_id = ?
                        """,
                        (self._run_id, durable.operation_id),
                    )
                )
                if existing is not None:
                    if _text(existing, "digest") != prepared.stored.digest:
                        raise ExecutionJournalConflict(
                            "compute operation has different payload evidence"
                        )
                    return (
                        CommittedPayloadEvidence(
                            ref=_text(existing, "ref"),
                            content_hash=_text(existing, "content_hash"),
                        ),
                        False,
                    )
                _publish_ref(connection, self._run_id, ref, prepared.stored)
                connection.execute(
                    """
                    INSERT INTO execution_payload_evidence(
                        run_id, operation_id, content_hash, ref, digest
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._run_id,
                        durable.operation_id,
                        durable.content_hash,
                        ref,
                        prepared.stored.digest,
                    ),
                )
                return (
                    CommittedPayloadEvidence(
                        ref=ref,
                        content_hash=durable.content_hash,
                    ),
                    True,
                )

            return commit_prepared()
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to commit payload evidence: {error}"
            ) from error


def _dataset_ref(dataset_id: str) -> str:
    return dataset_content_ref(
        dataset_id=dataset_id,
        kind=MEASUREMENT_DATASET_KIND,
    )


def _operation_ref(namespace: str, operation_id: str) -> str:
    digest = hashlib.sha256(operation_id.encode()).hexdigest()
    return f"{namespace}/{digest}.json"


def _batch_content_hash(entries: tuple[ExecutionTransition, ...]) -> str:
    content = json.dumps(
        [entry.model_dump(mode="json") for entry in entries],
        allow_nan=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _batch_rows(
    connection: sqlite3.Connection,
    run_id: str,
    first_sequence: int,
    transition_count: int,
) -> list[sqlite3.Row]:
    rows = _all(
        connection.execute(
            """
            SELECT ref, digest FROM execution_journal_entries
            WHERE run_id = ? AND sequence >= ? AND sequence < ?
            ORDER BY sequence
            """,
            (
                run_id,
                first_sequence,
                first_sequence + transition_count,
            ),
        )
    )
    if len(rows) != transition_count:
        raise ExecutionJournalError(
            "execution transition batch references incomplete journal entries"
        )
    return rows


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
    ref: str,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=seal.operation_id,
        dataset_content_hash=seal.dataset_content_hash,
        dataset_ref=ref,
    )


def _collection_receipt(
    chunk: CollectionChunk,
    ref: str,
) -> CollectionChunkReceipt:
    return CollectionChunkReceipt(
        operation_id=chunk.operation_id,
        ref=ref,
        content_hash=chunk.content_hash,
    )


def _dataset_sealed(
    connection: sqlite3.Connection,
    run_id: str,
    dataset_id: str,
) -> bool:
    return (
        _one(
            connection.execute(
                """
                SELECT 1 AS sealed FROM execution_measurement_seals
                WHERE run_id = ? AND dataset_id = ?
                """,
                (run_id, dataset_id),
            )
        )
        is not None
    )


def _measurement_rows(
    connection: sqlite3.Connection,
    run_id: str,
    dataset_id: str,
) -> list[sqlite3.Row]:
    return _all(
        connection.execute(
            """
            SELECT * FROM execution_measurement_appends
            WHERE run_id = ? AND dataset_id = ?
            ORDER BY start_index
            """,
            (run_id, dataset_id),
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
        INSERT INTO run_repository_refs(run_id, ref, digest, size)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id, ref) DO UPDATE SET
            digest = excluded.digest,
            size = excluded.size
        """,
        (run_id, ref, stored.digest, stored.size),
    )


@contextmanager
def _transaction(
    runs: SQLiteRunRepository,
) -> Generator[sqlite3.Connection]:
    with closing(_connect(runs)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


def _connect(runs: SQLiteRunRepository) -> sqlite3.Connection:
    connection = sqlite3.connect(
        runs.database,
        isolation_level=None,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])
