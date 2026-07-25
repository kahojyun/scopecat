from __future__ import annotations

import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from typing import override

import pytest

from scopecat.adapters.sqlite import (
    SQLiteCollectionRecordRepository,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.adapters.sqlite.execution import ExecutionJournalConflict
from scopecat.execution.ports.journal import (
    ExecutionJournal,
    ExecutionJournalError,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import InstrumentReadback
from tests.contracts.execution_port_contracts import (
    ExecutionJournalContract,
    MeasurementDatasetWriterContract,
    PayloadEvidenceCommitterContract,
)


def _runs(tmp_path: Path) -> SQLiteRunRepository:
    SQLiteProjectStore(
        tmp_path / "control.sqlite3",
        tmp_path / "objects",
    ).bootstrap()
    runs = SQLiteRunRepository(
        tmp_path / "control.sqlite3",
        tmp_path / "objects",
    )
    return runs


@contextmanager
def _sqlite_transaction(
    runs: SQLiteRunRepository,
) -> Generator[sqlite3.Connection]:
    connection = sqlite3.connect(
        runs.database,
        isolation_level=None,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        connection.close()


def _append(run_id: str, *, value: float = 1) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend(
        run_id=run_id,
        dataset_id="raw-measurements",
        recording_contract_fingerprint="recording.v1",
        start_index=0,
        records=(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id="point-0",
                point_index=0,
                coordinates={},
                observables={"signal": Quantity(value=value, unit="ratio")},
            ),
        ),
    )


def _seal(append: MeasurementDatasetAppend) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
        dataset_id=append.dataset_id,
        recording_contract_fingerprint=append.recording_contract_fingerprint,
        point_count=len(append.records),
        dataset_content_hash=measurement_dataset_content_hash(
            recording_contract_fingerprint=append.recording_contract_fingerprint,
            append_content_hashes=(append.content_hash,),
        ),
    )


def _chunk(run_id: str, *, value: float = 1) -> CollectionChunk:
    return CollectionChunk(
        run_id=run_id,
        operation_id="point-0.collect.scope",
        command_content_hash="command-hash",
        point_index=0,
        instrument_id="scope",
        readback=InstrumentReadback(
            values={"signal": Quantity(value=value, unit="ratio")}
        ),
    )


def _payload(run_id: str) -> PayloadEvidence:
    return PayloadEvidence(
        run_id=run_id,
        operation_id="compute-0",
        payload_id="payload-0",
        schema_id="payload.v1",
        content_hash="sha256:payload",
        fingerprint={"kind": "payload"},
    )


def _transitions(run_id: str) -> tuple[ExecutionTransition, ...]:
    return (
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="compute",
            effect="pure",
            state="started",
        ),
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="compute",
            effect="pure",
            state="completed",
        ),
    )


class TestSQLiteExecutionJournalContract(ExecutionJournalContract):
    @override
    def make_journal(self, tmp_path: Path, *, run_id: str) -> ExecutionJournal:
        return SQLiteExecutionJournal(_runs(tmp_path), run_id=run_id)

    @override
    def read_entries(
        self,
        journal: ExecutionJournal,
    ) -> tuple[ExecutionTransition, ...]:
        assert isinstance(journal, SQLiteExecutionJournal)
        return journal.entries()


class TestSQLiteMeasurementDatasetContract(MeasurementDatasetWriterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> MeasurementDatasetWriter:
        return SQLiteMeasurementDatasetRepository(_runs(tmp_path), run_id=run_id)


class TestSQLitePayloadEvidenceContract(PayloadEvidenceCommitterContract):
    @override
    def make_committer(
        self,
        tmp_path: Path,
        *,
        run_id: str,
    ) -> PayloadEvidenceCommitter:
        return SQLitePayloadEvidenceCommitter(_runs(tmp_path), run_id=run_id)


def test_execution_and_control_indexes_share_run_database(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    SQLiteProjectStore(database, tmp_path / "objects").bootstrap()
    runs = SQLiteRunRepository(database, tmp_path / "objects")
    journal = SQLiteExecutionJournal(runs, run_id="run-shared")

    committed = journal.append(
        ExecutionTransition(
            run_id="run-shared",
            operation_id="operation-0",
            stage="compute",
            effect="pure",
            state="completed",
        )
    )

    assert committed.sequence == 0
    assert (
        runs.read_model(
            "run-shared",
            "execution/journal/00000000.json",
            ExecutionTransition,
        )
        == committed
    )


def test_transition_batch_retry_replays_the_original_commit(tmp_path: Path) -> None:
    journal = SQLiteExecutionJournal(_runs(tmp_path), run_id="run-batch")
    transitions = _transitions("run-batch")

    first = journal.append_batch("batch-1", transitions)
    retry = journal.append_batch("batch-1", transitions)

    assert first.created
    assert not retry.created
    assert retry.transitions == first.transitions
    assert tuple(item.sequence for item in first.transitions) == (0, 1)
    assert journal.entries() == first.transitions

    with pytest.raises(ExecutionJournalConflict, match="different content"):
        journal.append_batch(
            "batch-1",
            (transitions[0].model_copy(update={"state": "completed"}),),
        )


def test_in_transaction_primitives_report_created_and_replay_durable_values(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    run_id = "run-in-transaction"
    journal = SQLiteExecutionJournal(runs, run_id=run_id)
    measurements = SQLiteMeasurementDatasetRepository(runs, run_id=run_id)
    collections = SQLiteCollectionRecordRepository(runs, run_id=run_id)
    payloads = SQLitePayloadEvidenceCommitter(runs, run_id=run_id)
    transitions = _transitions(run_id)
    append = _append(run_id)
    seal = _seal(append)
    chunk = _chunk(run_id)
    payload = _payload(run_id)
    prepared_append = measurements.prepare_append(append)
    prepared_seal = measurements.prepare_seal(seal)
    prepared_chunk = collections.prepare_commit(chunk)
    prepared_payload = payloads.prepare_commit(payload)

    with _sqlite_transaction(runs) as connection:
        transition, transition_created = journal.append_in_transaction(
            connection,
            transitions[0],
        )
        batch = journal.append_batch_in_transaction(
            connection,
            "batch-1",
            transitions,
        )
        batch_replay = journal.append_batch_in_transaction(
            connection,
            "batch-1",
            transitions,
        )
        append_receipt, append_created = measurements.append_in_transaction(
            connection,
            append,
        )
        append_replay, append_replay_created = (
            measurements.append_prepared_in_transaction(
                connection,
                prepared_append,
            )
        )
        seal_receipt, seal_created = measurements.seal_in_transaction(
            connection,
            seal,
        )
        seal_replay, seal_replay_created = measurements.seal_prepared_in_transaction(
            connection,
            prepared_seal,
        )
        sealed_append_replay, sealed_append_created = (
            measurements.append_prepared_in_transaction(
                connection,
                prepared_append,
            )
        )
        collection_receipt, collection_created = collections.commit_in_transaction(
            connection,
            chunk,
        )
        collection_replay, collection_replay_created = (
            collections.commit_prepared_in_transaction(
                connection,
                prepared_chunk,
            )
        )
        payload_receipt, payload_created = payloads.commit_in_transaction(
            connection,
            payload,
        )
        payload_replay, payload_replay_created = (
            payloads.commit_prepared_in_transaction(
                connection,
                prepared_payload,
            )
        )

        assert transition_created
        assert transition.sequence == 0
        assert batch.created
        assert not batch_replay.created
        assert batch_replay.transitions == batch.transitions
        assert append_created
        assert not append_replay_created
        assert append_replay == append_receipt
        assert seal_created
        assert not seal_replay_created
        assert seal_replay == seal_receipt
        assert not sealed_append_created
        assert sealed_append_replay == append_receipt
        assert collection_created
        assert not collection_replay_created
        assert collection_replay == collection_receipt
        assert collections.resolve_in_transaction(connection, collection_receipt) == (
            chunk
        )
        assert payload_created
        assert not payload_replay_created
        assert payload_replay == payload_receipt


def test_in_transaction_primitive_does_not_commit_its_connection(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    journal = SQLiteExecutionJournal(runs, run_id="run-rollback")
    connection = sqlite3.connect(runs.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN IMMEDIATE")

    commit = journal.append_batch_in_transaction(
        connection,
        "batch-rollback",
        _transitions("run-rollback"),
    )

    assert commit.created
    assert connection.in_transaction
    connection.rollback()
    connection.close()
    assert journal.entries() == ()


def test_concurrent_transition_batch_replay_has_one_creator(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    journals = (
        SQLiteExecutionJournal(runs, run_id="run-batch-concurrent"),
        SQLiteExecutionJournal(runs, run_id="run-batch-concurrent"),
    )
    transitions = _transitions("run-batch-concurrent")
    barrier = Barrier(2)

    def commit(journal: SQLiteExecutionJournal) -> tuple[str, bool]:
        barrier.wait()
        with _sqlite_transaction(runs) as connection:
            result = journal.append_batch_in_transaction(
                connection,
                "batch-1",
                transitions,
            )
            return (
                ",".join(
                    transition.model_dump_json() for transition in result.transitions
                ),
                result.created,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        committed = tuple(pool.map(commit, journals))

    assert committed[0][0] == committed[1][0]
    assert sorted(created for _value, created in committed) == [False, True]


def test_two_measurement_connections_replay_and_conflict_by_canonical_slot(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    first = SQLiteMeasurementDatasetRepository(runs, run_id="run-measurement")
    second = SQLiteMeasurementDatasetRepository(runs, run_id="run-measurement")
    append = _append("run-measurement")
    barrier = Barrier(2)

    def commit(
        repository: SQLiteMeasurementDatasetRepository,
    ) -> tuple[str, bool]:
        barrier.wait()
        prepared = repository.prepare_append(append.model_copy(deep=True))
        with _sqlite_transaction(runs) as connection:
            receipt, created = repository.append_prepared_in_transaction(
                connection,
                prepared,
            )
            return receipt.model_dump_json(), created

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(commit, (first, second)))

    assert len({receipt for receipt, _created in receipts}) == 1
    assert sorted(created for _receipt, created in receipts) == [False, True]
    assert len(first.measurements()) == 1
    index = first.append_indices()[0]
    assert index.operation_id == append.operation_id
    assert index.append_content_hash == append.content_hash
    assert index.record_count == 1
    with pytest.raises(ExecutionJournalConflict):
        second.append(_append("run-measurement", value=2))


def test_measurements_can_select_one_canonical_dataset(tmp_path: Path) -> None:
    repository = SQLiteMeasurementDatasetRepository(
        _runs(tmp_path),
        run_id="run-measurement",
    )
    raw = _append("run-measurement")
    derived = _append("run-measurement", value=2).model_copy(
        update={"dataset_id": "derived-measurements"}
    )

    repository.append(raw)
    repository.append(derived)

    assert repository.measurements(dataset_id="raw-measurements") == raw.records
    assert repository.measurements(dataset_id="derived-measurements") == (
        derived.records
    )
    assert len(repository.measurements()) == 2


def test_measurement_replay_rejects_mismatched_durable_operation_identity(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    append_repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-append-identity",
    )
    append = _append("run-append-identity")
    append_repository.append(append)
    seal_repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-seal-identity",
    )
    seal_append = _append("run-seal-identity")
    seal = _seal(seal_append)
    seal_repository.append(seal_append)
    seal_repository.seal(seal)
    with sqlite3.connect(runs.database) as connection:
        connection.execute(
            """
            UPDATE execution_measurement_appends
            SET operation_id = 'different-append'
            WHERE run_id = ?
            """,
            (append.run_id,),
        )
        connection.execute(
            """
            UPDATE execution_measurement_seals
            SET operation_id = 'different-seal'
            WHERE run_id = ?
            """,
            (seal.run_id,),
        )

    with pytest.raises(ExecutionJournalConflict, match="different content"):
        append_repository.append(append)
    with pytest.raises(ExecutionJournalConflict, match="different content"):
        seal_repository.seal(seal)


def test_collection_commit_resolve_receipts_and_cross_connection_conflict(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    first = SQLiteCollectionRecordRepository(runs, run_id="run-collection")
    second = SQLiteCollectionRecordRepository(runs, run_id="run-collection")
    chunk = _chunk("run-collection")

    receipt = first.commit(chunk)

    assert second.commit(chunk.model_copy(deep=True)) == receipt
    assert second.resolve(receipt) == chunk
    assert second.receipts() == (receipt,)
    with pytest.raises(ExecutionJournalConflict):
        second.commit(_chunk("run-collection", value=2))
    for changed in (
        {"operation_id": "other"},
        {"ref": "execution/readbacks/other.json"},
        {"content_hash": "other"},
    ):
        with pytest.raises(ExecutionJournalConflict):
            first.resolve(receipt.model_copy(update=changed))


def test_payload_conflict_is_visible_across_connections(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    first = SQLitePayloadEvidenceCommitter(runs, run_id="run-payload")
    second = SQLitePayloadEvidenceCommitter(runs, run_id="run-payload")
    evidence = PayloadEvidence(
        run_id="run-payload",
        operation_id="compute-0",
        payload_id="payload-0",
        schema_id="payload.v1",
        content_hash="sha256:payload",
        fingerprint={"kind": "payload"},
    )

    committed = first.commit(evidence)

    assert second.commit(evidence.model_copy(deep=True)) == committed
    with pytest.raises(ExecutionJournalConflict):
        second.commit(
            evidence.model_copy(update={"fingerprint": {"kind": "different"}})
        )


def test_index_failure_rolls_back_collection_ref(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteCollectionRecordRepository(runs, run_id="run-rollback")
    with sqlite3.connect(runs.database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_collection_index
            BEFORE INSERT ON execution_collections
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END
            """
        )

    with pytest.raises(ExecutionJournalError) as captured:
        repository.commit(_chunk("run-rollback"))

    assert not isinstance(captured.value, ExecutionJournalConflict)
    assert repository.receipts() == ()
    assert not runs.exists("run-rollback", "execution/readbacks")
    with sqlite3.connect(runs.database) as connection:
        connection.execute("DROP TRIGGER reject_collection_index")
    receipt = repository.commit(_chunk("run-rollback"))
    assert repository.resolve(receipt).content_hash == receipt.content_hash


def test_collection_resolve_rejects_unbacked_receipt(tmp_path: Path) -> None:
    repository = SQLiteCollectionRecordRepository(
        _runs(tmp_path),
        run_id="run-unbacked",
    )

    with pytest.raises(ExecutionJournalConflict):
        repository.resolve(
            CollectionChunkReceipt(
                operation_id="missing",
                ref=(
                    "execution/readbacks/"
                    "ffa63583dfa6706b87d284b86b0d693a161e4840aad2c5cf6b5d27c3b9621f7d"
                    ".json"
                ),
                content_hash="missing",
            )
        )
