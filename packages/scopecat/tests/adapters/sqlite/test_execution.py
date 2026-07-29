from __future__ import annotations

import json
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
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
    execution_transition_identity,
)
from scopecat.records.measurement import (
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
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
                observables={
                    "signal": MeasurementScalar.create(
                        dtype="float64",
                        value=value,
                        unit="ratio",
                    )
                },
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


def _commit_append(
    runs: SQLiteRunRepository,
    repository: SQLiteMeasurementDatasetRepository,
    append: MeasurementDatasetAppend,
) -> None:
    prepared = repository.prepare_append(append)
    with _sqlite_transaction(runs) as connection:
        repository.append_prepared_in_transaction(connection, prepared)


def _commit_seal(
    runs: SQLiteRunRepository,
    repository: SQLiteMeasurementDatasetRepository,
    seal: MeasurementDatasetSeal,
) -> None:
    prepared = repository.prepare_seal(seal)
    with _sqlite_transaction(runs) as connection:
        repository.seal_prepared_in_transaction(connection, prepared)


def _transitions(run_id: str) -> tuple[ExecutionTransition, ...]:
    return (
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="apply_state",
            effect="state_write",
            state="started",
        ),
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="apply_state",
            effect="state_write",
            state="completed",
        ),
    )


def test_execution_transitions_are_canonical_durable_events(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    SQLiteProjectStore(database, tmp_path / "objects").bootstrap()
    runs = SQLiteRunRepository(database, tmp_path / "objects")
    journal = SQLiteExecutionJournal(runs, run_id="run-shared")

    committed = journal.append(
        ExecutionTransition(
            run_id="run-shared",
            operation_id="operation-0",
            stage="apply_state",
            effect="state_write",
            state="completed",
        )
    )

    assert committed.sequence == 0
    with sqlite3.connect(database) as connection:
        event = connection.execute(
            """
            SELECT kind, run_sequence, payload_json
            FROM durable_events
            WHERE run_id = ?
            """,
            ("run-shared",),
        ).fetchone()
    assert event is not None
    assert event[0] == "execution_transition_committed"
    assert event[1] == 0
    assert json.loads(event[2])["operation_id"] == committed.operation_id


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
        _commit_append(
            runs,
            second,
            _append("run-measurement", value=2),
        )


def test_unavailable_measurement_round_trips_through_dataset_storage(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-unavailable",
    )
    unavailable = MeasurementUnavailable.create(
        reason="overload",
        dtype="float64",
        unit="V",
        shape=(2,),
        metadata={"status_register": 4},
    )
    append = MeasurementDatasetAppend(
        run_id="run-unavailable",
        recording_contract_fingerprint="recording.v1",
        start_index=0,
        records=(
            MeasurementRecord(
                run_id="run-unavailable",
                logical_point_id="point-0",
                point_index=0,
                coordinates={},
                observables={"signal": unavailable},
            ),
        ),
    )

    _commit_append(runs, repository, append)

    [record] = repository.measurements()
    restored = record.observables["signal"]
    assert isinstance(restored, MeasurementUnavailable)
    assert restored == unavailable


def test_measurement_replay_rejects_mismatched_durable_operation_identity(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    append_repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-append-identity",
    )
    append = _append("run-append-identity")
    _commit_append(runs, append_repository, append)
    seal_repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-seal-identity",
    )
    seal_append = _append("run-seal-identity")
    seal = _seal(seal_append)
    _commit_append(runs, seal_repository, seal_append)
    _commit_seal(runs, seal_repository, seal)
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
        _commit_append(runs, append_repository, append)
    with pytest.raises(ExecutionJournalConflict, match="different content"):
        _commit_seal(runs, seal_repository, seal)
