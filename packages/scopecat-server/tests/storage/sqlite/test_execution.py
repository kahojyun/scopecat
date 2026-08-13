from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Literal

import pytest
from scopecat.daemon.points import (
    RunPointDecisionCommand,
    RunPointEnqueueCommand,
    RunPointPlanCloseCommand,
    RunPointProposalAttemptView,
)
from scopecat.kernel.points import PointProposalAttempt
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
)
from scopecat.kernel.quantity import Quantity
from scopecat.measurements import recording_arrow
from scopecat.records.execution_journal import (
    ExecutionTransition,
    execution_transition_content_hash,
    execution_transition_identity,
)
from scopecat.records.measurement import (
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementPointCloudPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat_testkit.server.runtime import (
    SQLiteTestExecutionJournal as SQLiteExecutionJournal,
)

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.execution import (
    ExecutionJournalConflict,
    SQLiteMeasurementDatasetRepository,
    SQLiteRunPointLedger,
)
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository


def _runs(tmp_path: Path) -> SQLiteRunRepository:
    sqlite = SQLiteDatabase(tmp_path / "control.sqlite3")
    SQLiteProjectStore(
        sqlite,
        tmp_path / "objects",
    ).bootstrap()
    runs = SQLiteRunRepository(
        sqlite,
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


def test_adaptive_point_ledger_persists_idempotent_decisions_and_closure(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    run_id = "adaptive-ledger-run"
    with _sqlite_transaction(runs) as connection:
        connection.execute(
            """
            INSERT INTO scheduler_runs(
                submission_id, run_id, state, updated_at, admission_json
            )
            VALUES (?, ?, 'queued', ?, '{}')
            """,
            ("adaptive-ledger-submission", run_id, datetime.now(UTC).isoformat()),
        )
        ledger = SQLiteRunPointLedger(runs, run_id=run_id)
        initialized = ledger.initialize_in_transaction(
            connection,
            operation_id="initialize",
            initial_point_count=2,
            point_limit=5,
            plan_closed=False,
        )
        first_command = _point_decision_command(
            operation_id="decision-1",
            based_on_completed_point_count=2,
        )
        accepted = ledger.append_decision_in_transaction(
            connection,
            first_command,
            completed_point_count=2,
        )
        retry = ledger.append_decision_in_transaction(
            connection,
            first_command,
            completed_point_count=2,
        )
        second = ledger.append_decision_in_transaction(
            connection,
            _point_decision_command(
                operation_id="decision-2",
                based_on_completed_point_count=3,
            ),
            completed_point_count=3,
        )
        rejected = ledger.append_decision_in_transaction(
            connection,
            _point_decision_command(
                operation_id="decision-3",
                based_on_completed_point_count=1,
                outcome="rejected",
                reason="stale optimizer state",
            ),
            completed_point_count=4,
        )
        with pytest.raises(ExecutionJournalConflict, match="stale completed"):
            ledger.append_decision_in_transaction(
                connection,
                _point_decision_command(
                    operation_id="stale-accepted",
                    based_on_completed_point_count=1,
                ),
                completed_point_count=4,
            )
        close = RunPointPlanCloseCommand(
            lease_id="lease-1",
            operation_id="close",
            based_on_completed_point_count=4,
            reason="optimizer converged",
        )
        closed = ledger.close_in_transaction(
            connection,
            close,
            completed_point_count=4,
        )
        close_retry = ledger.close_in_transaction(
            connection,
            close,
            completed_point_count=4,
        )

    assert initialized.accepted_point_count == 2
    assert accepted == retry
    assert accepted.accepted_point is not None
    assert accepted.accepted_point.point_index == 2
    assert second.accepted_point is not None
    assert second.accepted_point.point_index == 3
    assert rejected.outcome == "rejected"
    assert closed == close_retry
    assert closed.accepted_point_count == 4
    assert closed.decision_count == 3
    assert closed.plan_closed
    assert closed.stop_reason == "optimizer converged"
    assert SQLiteRunPointLedger(runs, run_id=run_id).read() == closed
    with runs.sqlite.read_transaction() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS point_count
            FROM execution_run_points
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    assert row is not None
    assert row["point_count"] == 2


def _point_decision_command(
    *,
    operation_id: str,
    based_on_completed_point_count: int,
    outcome: Literal["accepted", "rejected"] = "accepted",
    reason: str | None = None,
) -> RunPointDecisionCommand:
    candidate = PointProposalAttempt(
        {"frequency": Quantity(5.2, "GHz")},
        source="optimizer",
        based_on_completed_point_count=based_on_completed_point_count,
    )
    return RunPointDecisionCommand(
        lease_id="lease-1",
        operation_id=operation_id,
        proposal=RunPointProposalAttemptView(
            coordinates={"frequency": Quantity(5.2, "GHz")},
            proposal_fingerprint=candidate.proposal_fingerprint,
            source="optimizer",
            based_on_completed_point_count=based_on_completed_point_count,
        ),
        outcome=outcome,
        reason=reason,
    )


def test_operator_point_queue_is_fifo_bounded_and_resolved_by_decisions(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    run_id = "operator-queue-run"
    queued_candidate = PointProposalAttempt(
        {"frequency": Quantity(5.15, "GHz")},
        source="operator",
    )
    enqueue = RunPointEnqueueCommand(
        request_id="queue-1",
        coordinate_mode="free",
        coordinates={"frequency": Quantity(5.15, "GHz")},
    )
    second_enqueue = enqueue.model_copy(update={"request_id": "queue-2"})
    with _sqlite_transaction(runs) as connection:
        connection.execute(
            """
            INSERT INTO scheduler_runs(
                submission_id, run_id, state, updated_at, admission_json
            )
            VALUES (?, ?, 'leased', ?, '{}')
            """,
            ("operator-queue-submission", run_id, datetime.now(UTC).isoformat()),
        )
        ledger = SQLiteRunPointLedger(runs, run_id=run_id)
        ledger.initialize_in_transaction(
            connection,
            operation_id="initialize",
            initial_point_count=1,
            point_limit=3,
            plan_closed=False,
        )
        first, first_created = ledger.enqueue_in_transaction(
            connection,
            enqueue,
            resolved_coordinates=enqueue.coordinates,
        )
        retry, retry_created = ledger.enqueue_in_transaction(
            connection,
            enqueue,
            resolved_coordinates=enqueue.coordinates,
        )
        second, _ = ledger.enqueue_in_transaction(
            connection,
            second_enqueue,
            resolved_coordinates=second_enqueue.coordinates,
        )
        with pytest.raises(ExecutionJournalConflict, match="remaining budget"):
            ledger.enqueue_in_transaction(
                connection,
                enqueue.model_copy(update={"request_id": "queue-3"}),
                resolved_coordinates=enqueue.coordinates,
            )

    assert first == retry
    assert first_created
    assert not retry_created
    assert ledger.next_pending() == first
    normalized = PointProposalAttempt(
        queued_candidate.coordinates,
        source="operator",
        based_on_completed_point_count=1,
    )
    with _sqlite_transaction(runs) as connection:
        decision = ledger.append_decision_in_transaction(
            connection,
            RunPointDecisionCommand(
                lease_id="lease-1",
                operation_id="decision-1",
                operator_request_id=first.request.request_id,
                proposal=RunPointProposalAttemptView(
                    coordinates={"frequency": Quantity(5.15, "GHz")},
                    proposal_fingerprint=normalized.proposal_fingerprint,
                    source="operator",
                    based_on_completed_point_count=1,
                ),
                outcome="accepted",
            ),
            completed_point_count=1,
        )
        closed = ledger.close_in_transaction(
            connection,
            RunPointPlanCloseCommand(
                lease_id="lease-1",
                operation_id="close",
                based_on_completed_point_count=2,
                reason="operator sweep complete",
            ),
            completed_point_count=2,
        )

    queue = ledger.queue()
    assert decision.accepted_point is not None
    assert decision.accepted_point.point_index == 1
    assert decision.operator_request_id == first.request.request_id
    assert closed.plan_closed
    assert queue.items[0].status == "accepted"
    assert queue.items[0].accepted_point_index == 1
    assert queue.items[1].request.request_id == second.request.request_id
    assert queue.items[1].status == "cancelled"
    assert queue.items[1].reason == "point plan closed: operator sweep complete"


def _header(
    run_id: str,
    *,
    point_count: int = 1,
) -> MeasurementDatasetHeader:
    return MeasurementDatasetHeader(
        run_id=run_id,
        recording_contract_fingerprint="recording.v1",
        dataset_schema=MeasurementDatasetSchema(
            dataset_id="raw-measurements",
            point_domain=MeasurementPointCloudPointDomain(columns=()),
            dimensions=[
                MeasurementDimension(id="point", kind="point", size=point_count)
            ],
            variables=(
                MeasurementVariable(
                    id="signal",
                    role="observable",
                    dtype="float64",
                    unit="ratio",
                    dims=("point",),
                ),
            ),
            primary_observables=("signal",),
        ),
        expected_record_count=point_count,
        record_count_limit=point_count,
    )


def _append(
    header: MeasurementDatasetHeader,
    *,
    point_index: int = 0,
    value: float = 1,
) -> MeasurementDatasetAppend:
    return MeasurementDatasetAppend(
        run_id=header.run_id,
        header_content_hash=header.content_hash,
        start_index=point_index,
        records=(
            MeasurementRecord(
                run_id=header.run_id,
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


def _seal(
    header: MeasurementDatasetHeader,
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetSeal:
    return MeasurementDatasetSeal(
        run_id=append.run_id,
        header_content_hash=header.content_hash,
        point_count=len(append.records),
        dataset_content_hash=measurement_dataset_content_hash(
            header_content_hash=header.content_hash,
            record_content_hashes=append.record_content_hashes,
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


def _commit_header(
    runs: SQLiteRunRepository,
    repository: SQLiteMeasurementDatasetRepository,
    header: MeasurementDatasetHeader,
) -> None:
    prepared = repository.prepare_header(header)
    with _sqlite_transaction(runs) as connection:
        repository.header_prepared_in_transaction(connection, prepared)


def _commit_seal(
    runs: SQLiteRunRepository,
    repository: SQLiteMeasurementDatasetRepository,
    seal: MeasurementDatasetSeal,
) -> None:
    prepared = repository.prepare_seal(seal)
    with _sqlite_transaction(runs) as connection:
        repository.seal_prepared_in_transaction(connection, prepared)


def test_measurement_repository_reuses_schema_hash_for_appends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-cached-schema")
    header = _header("run-cached-schema", point_count=2)
    original = recording_arrow.measurement_dataset_schema_hash
    hash_calls = 0

    def counted_hash(dataset_schema: MeasurementDatasetSchema) -> str:
        nonlocal hash_calls
        hash_calls += 1
        return original(dataset_schema)

    monkeypatch.setattr(
        recording_arrow,
        "measurement_dataset_schema_hash",
        counted_hash,
    )

    _commit_header(runs, repository, header)
    _commit_append(runs, repository, _append(header, point_index=0))
    _commit_append(runs, repository, _append(header, point_index=1))

    assert hash_calls == 1


def _transitions(run_id: str) -> tuple[ExecutionTransition, ...]:
    return (
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="domain_execute",
            effect="read",
            state="started",
        ),
        ExecutionTransition(
            run_id=run_id,
            operation_id="operation-0",
            stage="domain_execute",
            effect="read",
            state="completed",
        ),
    )


def test_execution_transitions_are_canonical_durable_events(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    sqlite = SQLiteDatabase(database)
    SQLiteProjectStore(sqlite, tmp_path / "objects").bootstrap()
    runs = SQLiteRunRepository(sqlite, tmp_path / "objects")
    journal = SQLiteExecutionJournal(runs, run_id="run-shared")

    committed = journal.append(
        ExecutionTransition(
            run_id="run-shared",
            operation_id="operation-0",
            stage="domain_execute",
            effect="read",
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


def test_transition_claim_rejects_operation_reentry(tmp_path: Path) -> None:
    journal = SQLiteExecutionJournal(_runs(tmp_path), run_id="run-claim")
    started = _transitions("run-claim")[0]

    claimed = journal.claim(started)

    assert claimed.sequence == 0
    with pytest.raises(ExecutionJournalConflict, match="already claimed"):
        journal.claim(started)
    assert journal.entries() == (claimed,)


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
        stage="domain_execute",
        effect="read",
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
    header = _header(run_id)
    append = _append(header)
    seal = _seal(header, append)
    prepared_header = measurements.prepare_header(header)
    prepared_append = measurements.prepare_append(
        append,
        dataset_schema=header.dataset_schema,
    )
    prepared_seal = measurements.prepare_seal(seal)

    with _sqlite_transaction(runs) as connection:
        header_receipt, header_created = measurements.header_prepared_in_transaction(
            connection,
            prepared_header,
        )
        header_replay, header_replay_created = (
            measurements.header_prepared_in_transaction(
                connection,
                prepared_header,
            )
        )
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
        assert header_created
        assert not header_replay_created
        assert header_replay == header_receipt
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
    header = _header("run-measurement")
    _commit_header(runs, first, header)
    append = _append(header)
    barrier = Barrier(2)

    def commit(
        repository: SQLiteMeasurementDatasetRepository,
    ) -> tuple[str, bool]:
        barrier.wait()
        prepared = repository.prepare_append(append)
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
            _append(header, value=2),
        )


def test_measurement_page_reads_intersecting_chunks_and_live_schema(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-page")
    header = _header("run-page", point_count=3)
    _commit_header(runs, repository, header)
    first = _append(header, point_index=0, value=1)
    second = _append(header, point_index=1, value=2)
    _commit_append(runs, repository, first)
    _commit_append(runs, repository, second)

    items, next_offset, schema, snapshot_size = repository.measurement_page(
        limit=1, offset=0
    )
    _commit_append(
        runs,
        repository,
        _append(header, point_index=2, value=3),
    )
    later, later_offset, later_schema, later_snapshot_size = (
        repository.measurement_page(
            limit=1,
            offset=1,
            snapshot_size=snapshot_size,
            include_schema=False,
        )
    )
    current, current_offset, _current_schema, current_snapshot_size = (
        repository.measurement_page(limit=10, offset=0)
    )

    assert [record.point_index for record in items] == [0]
    assert next_offset == 1
    assert [record.point_index for record in later] == [1]
    assert later_offset is None
    assert snapshot_size == later_snapshot_size == 2
    assert [record.point_index for record in current] == [0, 1, 2]
    assert current_offset is None
    assert current_snapshot_size == 3
    assert schema == header.dataset_schema
    assert later_schema is None


def test_measurement_page_pushes_variable_selection_into_arrow_chunks(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-columns")
    base = _header("run-columns")
    header = base.model_copy(
        update={
            "dataset_schema": base.dataset_schema.model_copy(
                update={
                    "variables": (
                        MeasurementVariable(
                            id="frequency",
                            role="coordinate",
                            dtype="float64",
                            unit="Hz",
                            dims=("point",),
                        ),
                        *base.dataset_schema.variables,
                    ),
                    "primary_coordinates": ("frequency",),
                }
            )
        }
    )
    _commit_header(runs, repository, header)
    append = _append(header).model_copy(
        update={
            "records": (
                _append(header)
                .records[0]
                .model_copy(
                    update={
                        "coordinates": {
                            "frequency": MeasurementScalar.create(
                                dtype="float64",
                                value=5e9,
                                unit="Hz",
                            )
                        }
                    }
                ),
            )
        }
    )
    _commit_append(runs, repository, append)

    items, next_offset, schema, snapshot_size = repository.measurement_page(
        limit=1,
        offset=0,
        variable_ids=("signal",),
    )

    assert next_offset is None
    assert snapshot_size == 1
    assert schema == header.dataset_schema
    assert items[0].coordinates == {}
    assert tuple(items[0].observables) == ("signal",)


def test_measurement_records_at_reads_only_selected_durable_points(
    tmp_path: Path,
) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-selection")
    header = _header("run-selection", point_count=5)
    _commit_header(runs, repository, header)
    for start_index in (0, 2):
        append = MeasurementDatasetAppend(
            run_id=header.run_id,
            header_content_hash=header.content_hash,
            start_index=start_index,
            records=tuple(
                _append(
                    header,
                    point_index=point_index,
                    value=point_index,
                ).records[0]
                for point_index in range(start_index, start_index + 2)
            ),
        )
        _commit_append(runs, repository, append)

    records = repository.measurement_records_at((3, 1, 4))

    assert [record.point_index for record in records] == [3, 1]
    assert [record.observables["signal"] for record in records] == [
        MeasurementScalar.create(dtype="float64", value=3, unit="ratio"),
        MeasurementScalar.create(dtype="float64", value=1, unit="ratio"),
    ]


def test_measurement_header_makes_an_empty_dataset_readable(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-empty")
    header = _header("run-empty", point_count=0)
    _commit_header(runs, repository, header)
    seal = MeasurementDatasetSeal(
        run_id=header.run_id,
        header_content_hash=header.content_hash,
        point_count=0,
        dataset_content_hash=measurement_dataset_content_hash(
            header_content_hash=header.content_hash,
            record_content_hashes=(),
        ),
    )
    _commit_seal(runs, repository, seal)

    items, next_offset, schema, snapshot_size = repository.measurement_page(
        limit=10, offset=0
    )

    assert items == ()
    assert next_offset is None
    assert snapshot_size == 0
    assert schema == header.dataset_schema
    assert repository.measurements() == ()


def test_measurement_header_rejects_a_changed_live_schema(tmp_path: Path) -> None:
    runs = _runs(tmp_path)
    repository = SQLiteMeasurementDatasetRepository(runs, run_id="run-schema")
    header = _header("run-schema")
    _commit_header(runs, repository, header)
    changed_schema = header.dataset_schema.model_copy(
        update={"metadata": {"revision": 2}}
    )

    with pytest.raises(ExecutionJournalConflict, match="different content"):
        _commit_header(
            runs,
            repository,
            header.model_copy(update={"dataset_schema": changed_schema}),
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
        unit="ratio",
        shape=(),
        metadata={"status_register": 4},
    )
    header = _header("run-unavailable")
    append = MeasurementDatasetAppend(
        run_id="run-unavailable",
        header_content_hash=header.content_hash,
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

    _commit_header(runs, repository, header)
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
    append_header = _header("run-append-identity")
    _commit_header(runs, append_repository, append_header)
    append = _append(append_header)
    _commit_append(runs, append_repository, append)
    seal_repository = SQLiteMeasurementDatasetRepository(
        runs,
        run_id="run-seal-identity",
    )
    seal_header = _header("run-seal-identity")
    _commit_header(runs, seal_repository, seal_header)
    seal_append = _append(seal_header)
    seal = _seal(seal_header, seal_append)
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
