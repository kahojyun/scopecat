from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import override

import pytest

from scopecat.adapters.sqlite import (
    SQLiteCollectionRecordRepository,
    SQLiteControlPlane,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    SQLiteRunRepository,
    bootstrap_execution_schema,
)
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
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import InstrumentReadback
from tests.contracts.execution_port_contracts import (
    ExecutionJournalContract,
    MeasurementDatasetWriterContract,
    PayloadEvidenceCommitterContract,
)


def _runs(tmp_path: Path) -> SQLiteRunRepository:
    runs = SQLiteRunRepository(
        tmp_path / "workspace.sqlite3",
        tmp_path / "objects",
    )
    runs.bootstrap()
    bootstrap_execution_schema(runs)
    return runs


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
    database = tmp_path / "workspace.sqlite3"
    control = SQLiteControlPlane(database)
    control.bootstrap()
    runs = SQLiteRunRepository(database, tmp_path / "objects")
    runs.bootstrap()
    bootstrap_execution_schema(runs)
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
    assert control.schema_version() == 1
    assert (
        runs.read_model(
            "run-shared",
            "execution/journal/00000000.json",
            ExecutionTransition,
        )
        == committed
    )


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
    ) -> str:
        barrier.wait()
        return repository.append(append.model_copy(deep=True)).model_dump_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(commit, (first, second)))

    assert len(set(receipts)) == 1
    assert len(first.measurements()) == 1
    index = first.append_indices()[0]
    assert index.operation_id == append.operation_id
    assert index.append_content_hash == append.content_hash
    assert index.record_count == 1
    with pytest.raises(ExecutionJournalError):
        second.append(_append("run-measurement", value=2))


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
    with pytest.raises(ExecutionJournalError):
        second.commit(_chunk("run-collection", value=2))
    for changed in (
        {"operation_id": "other"},
        {"ref": "execution/readbacks/other.json"},
        {"content_hash": "other"},
    ):
        with pytest.raises(ExecutionJournalError):
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
    with pytest.raises(ExecutionJournalError):
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

    with pytest.raises(ExecutionJournalError):
        repository.commit(_chunk("run-rollback"))

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

    with pytest.raises(ExecutionJournalError):
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
