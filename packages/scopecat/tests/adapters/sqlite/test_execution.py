from __future__ import annotations

import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from scopecat.adapters.sqlite import (
    SQLiteMeasurementDatasetRepository,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.adapters.sqlite.execution import ExecutionJournalConflict
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
    execution_transition_identity,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.sdk.journal import ExecutionJournalError
from tests.testkit.runtime import SQLiteTestExecutionJournal as SQLiteExecutionJournal


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


def _append(
    run_id: str,
    *,
    point_index: int = 0,
    value: float = 1,
) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend(
        run_id=run_id,
        recording_contract_fingerprint="recording.v1",
        start_index=point_index,
        records=(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id=f"point-{point_index}",
                point_index=point_index,
                coordinates={},
                observables={"signal": Quantity(value=value, unit="ratio")},
            ),
        ),
    )


def _seal(append: MeasurementDatasetAppend) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
        recording_contract_fingerprint=append.recording_contract_fingerprint,
        point_count=len(append.records),
        dataset_content_hash=measurement_dataset_content_hash(
            recording_contract_fingerprint=append.recording_contract_fingerprint,
            append_content_hashes=(append.content_hash,),
        ),
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


def _transition(run_id: str, ordinal: int) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=run_id,
        operation_id=f"contract.operation.{ordinal}",
        stage="compute",
        effect="pure",
        state="completed",
        evidence={"ordinal": ordinal},
    )


def _transition_body(transition: ExecutionTransition) -> dict[str, object]:
    return transition.model_dump(
        mode="python",
        exclude={"sequence", "timestamp"},
    )


def test_append_assigns_sequence_and_preserves_transition(tmp_path: Path) -> None:
    run_id = "run-journal-contract"
    journal = SQLiteExecutionJournal(_runs(tmp_path), run_id=run_id)
    first_input = _transition(run_id, 0)
    second_input = _transition(run_id, 1)

    first = journal.append(first_input)
    second = journal.append(second_input)

    assert first_input.sequence is None
    assert second_input.sequence is None
    assert first.sequence == 0
    assert second.sequence == 1
    assert _transition_body(first) == _transition_body(first_input)
    assert _transition_body(second) == _transition_body(second_input)
    assert journal.entries() == (first, second)


def test_concurrent_append_assigns_each_sequence_once(tmp_path: Path) -> None:
    run_id = "run-journal-concurrency-contract"
    journal = SQLiteExecutionJournal(_runs(tmp_path), run_id=run_id)

    def append_transition(ordinal: int) -> ExecutionTransition:
        return journal.append(_transition(run_id, ordinal))

    with ThreadPoolExecutor(max_workers=4) as executor:
        committed = tuple(executor.map(append_transition, range(12)))

    committed_sequences: list[int] = []
    for entry in committed:
        assert entry.sequence is not None
        committed_sequences.append(entry.sequence)
    assert sorted(committed_sequences) == list(range(12))

    stored = journal.entries()
    stored_sequences: list[int] = []
    for entry in stored:
        assert entry.sequence is not None
        stored_sequences.append(entry.sequence)
    assert stored_sequences == list(range(12))
    assert {entry.operation_id for entry in stored} == {
        f"contract.operation.{ordinal}" for ordinal in range(12)
    }


def test_replay_returns_the_same_exact_receipt(tmp_path: Path) -> None:
    run_id = "run-measurement-committer-contract"
    committer = SQLiteMeasurementDatasetRepository(_runs(tmp_path), run_id=run_id)
    append = _append(run_id)

    first = committer.append(append)
    repeated = committer.append(append.model_copy(deep=True))

    assert repeated == first
    assert first == MeasurementDatasetReceipt(
        operation_id=append.operation_id,
        dataset_content_hash=append.content_hash,
        dataset_ref=first.dataset_ref,
    )


def test_same_operation_rejects_different_content(tmp_path: Path) -> None:
    run_id = "run-measurement-conflict-contract"
    committer = SQLiteMeasurementDatasetRepository(_runs(tmp_path), run_id=run_id)
    append = _append(run_id)
    changed_record = append.records[0].model_copy(
        update={
            "observables": {"signal": Quantity(value=2.0, unit="ratio")},
        }
    )
    conflicting = append.model_copy(update={"records": (changed_record,)})
    assert conflicting.operation_id == append.operation_id
    assert conflicting.content_hash != append.content_hash

    committer.append(append)

    with pytest.raises(ExecutionJournalError):
        committer.append(conflicting)


def test_concurrent_replay_is_idempotent(tmp_path: Path) -> None:
    run_id = "run-measurement-concurrency-contract"
    committer = SQLiteMeasurementDatasetRepository(_runs(tmp_path), run_id=run_id)
    append = _append(run_id)

    def replay_append(_ordinal: int) -> MeasurementDatasetReceipt:
        return committer.append(append.model_copy(deep=True))

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = tuple(executor.map(replay_append, range(8)))

    assert len({receipt.model_dump_json() for receipt in receipts}) == 1


def test_seal_is_idempotent_and_rejects_later_appends(tmp_path: Path) -> None:
    run_id = "run-measurement-seal-contract"
    committer = SQLiteMeasurementDatasetRepository(_runs(tmp_path), run_id=run_id)
    append = _append(run_id)
    committer.append(append)
    seal = MeasurementDatasetSeal(
        run_id=run_id,
        recording_contract_fingerprint=append.recording_contract_fingerprint,
        point_count=1,
        dataset_content_hash=measurement_dataset_content_hash(
            recording_contract_fingerprint=append.recording_contract_fingerprint,
            append_content_hashes=(append.content_hash,),
        ),
    )

    first = committer.seal(seal)
    repeated = committer.seal(seal.model_copy(deep=True))

    assert repeated == first
    with pytest.raises(ExecutionJournalError):
        committer.append(_append(run_id, point_index=1))


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


def test_transition_retry_replays_the_original_commit(tmp_path: Path) -> None:
    journal = SQLiteExecutionJournal(_runs(tmp_path), run_id="run-transition")
    transition = _transitions("run-transition")[0]

    first = journal.append(transition)
    retry = journal.append(
        transition.model_copy(
            update={
                "sequence": 100,
                "timestamp": transition.timestamp + timedelta(seconds=1),
            }
        )
    )

    assert retry == first
    assert first.sequence == 0
    changed = journal.append(transition.model_copy(update={"state": "completed"}))
    assert changed.sequence == 1
    assert journal.entries() == (first, changed)


def test_transition_transport_identity_excludes_only_daemon_fields() -> None:
    selected = problem(
        "read_failed",
        "instrument read failed",
        phase=ProblemPhase.EXECUTION,
    )
    transition = ExecutionTransition(
        sequence=7,
        run_id="run-identity",
        operation_id="operation-1",
        stage="collect",
        effect="acquisition",
        state="failed",
        timestamp=datetime(2026, 7, 23, 9, tzinfo=UTC),
        point_index=3,
        instrument_id="scope-1",
        problems=(selected,),
        evidence={"reading": float("inf")},
    )

    identity = execution_transition_identity(transition)

    assert set(identity) == {
        "run_id",
        "operation_id",
        "stage",
        "effect",
        "state",
        "point_index",
        "instrument_id",
        "problems",
        "evidence",
    }
    original_hash = execution_transition_content_hash(transition)
    reassigned = transition.model_copy(
        update={
            "sequence": 8,
            "timestamp": transition.timestamp + timedelta(seconds=1),
        }
    )
    assert execution_transition_content_hash(reassigned) == original_hash
    changed = transition.model_copy(update={"evidence": {"reading": float("-inf")}})
    assert execution_transition_content_hash(changed) != original_hash
    nan_transition = transition.model_copy(
        update={"evidence": {"reading": float("nan")}}
    )
    assert execution_transition_content_hash(
        nan_transition
    ) == execution_transition_content_hash(nan_transition.model_copy(deep=True))


def test_in_transaction_primitives_report_created_and_replay_durable_values(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    run_id = "run-in-transaction"
    journal = SQLiteExecutionJournal(runs, run_id=run_id)
    measurements = SQLiteMeasurementDatasetRepository(runs, run_id=run_id)
    transitions = _transitions(run_id)
    append = _append(run_id)
    seal = _seal(append)
    prepared_append = measurements.prepare_append(append)
    prepared_seal = measurements.prepare_seal(seal)

    with _sqlite_transaction(runs) as connection:
        transition, transition_created = journal.append_in_transaction(
            connection,
            transitions[0],
        )
        transition_replay, transition_replay_created = journal.append_in_transaction(
            connection,
            transitions[0],
        )
        append_receipt, append_created = measurements.append_prepared_in_transaction(
            connection,
            prepared_append,
        )
        append_replay, append_replay_created = (
            measurements.append_prepared_in_transaction(
                connection,
                prepared_append,
            )
        )
        seal_receipt, seal_created = measurements.seal_prepared_in_transaction(
            connection,
            prepared_seal,
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
        assert transition_created
        assert transition.sequence == 0
        assert not transition_replay_created
        assert transition_replay == transition
        assert append_created
        assert not append_replay_created
        assert append_replay == append_receipt
        assert seal_created
        assert not seal_replay_created
        assert seal_replay == seal_receipt
        assert not sealed_append_created
        assert sealed_append_replay == append_receipt


def test_in_transaction_primitive_does_not_commit_its_connection(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    journal = SQLiteExecutionJournal(runs, run_id="run-rollback")
    connection = sqlite3.connect(runs.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN IMMEDIATE")

    _transition, created = journal.append_in_transaction(
        connection,
        _transitions("run-rollback")[0],
    )

    assert created
    assert connection.in_transaction
    connection.rollback()
    connection.close()
    assert journal.entries() == ()


def test_concurrent_transition_replay_has_one_creator(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    journals = (
        SQLiteExecutionJournal(runs, run_id="run-batch-concurrent"),
        SQLiteExecutionJournal(runs, run_id="run-batch-concurrent"),
    )
    transition = _transitions("run-batch-concurrent")[0]
    barrier = Barrier(2)

    def commit(journal: SQLiteExecutionJournal) -> tuple[str, bool]:
        barrier.wait()
        with _sqlite_transaction(runs) as connection:
            result, created = journal.append_in_transaction(
                connection,
                transition,
            )
            return result.model_dump_json(), created

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
    with pytest.raises(ExecutionJournalConflict):
        second.append(_append("run-measurement", value=2))


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
