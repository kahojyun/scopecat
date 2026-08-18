from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from scopecat.automation import (
    CalibrationCohortCreateCommand,
    CalibrationCohortCreateReceipt,
    CalibrationCohortGetQuery,
    CalibrationCohortGetReceipt,
    CalibrationCohortListQuery,
    CalibrationCohortMember,
    CalibrationCohortMemberListQuery,
    CalibrationCohortMemberSpec,
    CalibrationCohortSpec,
    CalibrationCohortSummary,
    CalibrationConfigSourceRef,
    CalibrationDefinitionRef,
    CalibrationForcedDueReason,
    CalibrationStatusQuery,
    CalibrationStatusReceipt,
    CalibrationSuccessPolicy,
    CalibrationSuccessPublication,
    CalibrationSuccessRef,
    CalibrationTargetRef,
    ProcedureCloseCommand,
    ProcedureCloseStatus,
    ProcedureDefinitionRef,
    ProcedureRun,
    ProcedureRunAttentionCommand,
    ProcedureRunListQuery,
    ProcedureRunPage,
    ProcedureRunState,
    ProcedureSubmitCommand,
    ProcedureWaitCommand,
    ProcedureWorkerLeaseAcquireCommand,
    RunTerminalWait,
    calibration_cohort_member_request_key,
    calibration_freshness_fingerprint,
    calibration_key,
)
from scopecat.config.registry.records import ConfigPublishOperation
from scopecat.config.registry.service import (
    ConfigRevision,
    DirectConfigRevisionSource,
    publish_config_revision,
    resolve_config_registry_config_source,
)
from scopecat.daemon.wire import (
    ConfigPublishCommand,
    ConfigPublishReceipt,
)
from scopecat.daemon.wire import (
    DirectConfigRevisionSource as WireDirectConfigRevisionSource,
)
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat_testkit.workflow_fixtures import load_config

from scopecat_server import BackendConflict, BackendNotFound, LocalDaemonRuntime
from scopecat_server.services.automation import AutomationService
from scopecat_server.services.calibration_cohorts import CalibrationCohortService
from scopecat_server.storage.sqlite import calibration_cohorts as calibration_storage
from scopecat_server.storage.sqlite.automation import (
    AutomationConflict,
    SQLiteAutomationStore,
)
from scopecat_server.storage.sqlite.calibration_cohorts import (
    CalibrationCohortConflict,
    SQLiteCalibrationCohortStore,
)
from scopecat_server.storage.sqlite.config_operations import SQLiteConfigOperationStore
from scopecat_server.storage.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

_START = datetime(2026, 8, 18, 9, tzinfo=UTC)
_DEFINITION_HASH = "sha256:" + "1" * 64
_PROCEDURE_HASH = "sha256:" + "2" * 64
_INPUT_HASH = "sha256:" + "3" * 64
_RESULT_INPUT_HASH = "sha256:" + "4" * 64


@dataclass(frozen=True, slots=True)
class _Harness:
    service: CalibrationCohortService
    automation: AutomationService
    store: SQLiteCalibrationCohortStore
    automation_store: SQLiteAutomationStore
    config_registry: SQLiteConfigRegistryStore
    source: CalibrationConfigSourceRef
    now: list[datetime]


def _harness(tmp_path: Path) -> _Harness:
    sqlite = SQLiteDatabase(tmp_path / "control.sqlite3")
    objects = tmp_path / "objects"
    SQLiteProjectStore(sqlite, objects).bootstrap()
    runs = SQLiteRunRepository(sqlite, objects)
    config_registry = SQLiteConfigRegistryStore(sqlite, runs=runs)
    publish_config_revision(
        revision=ConfigRevision(
            source=DirectConfigRevisionSource(load_config()),
            entry_id="calibration-baseline",
            actor="test",
        ),
        unit_of_work=config_registry.write_unit_of_work,
        expected_generation=0,
    )
    _, run_source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=config_registry.read_unit_of_work,
    )
    assert isinstance(run_source, ConfigRegistryRunConfigSource)
    source = CalibrationConfigSourceRef.from_run_config_source(run_source)
    now = [_START]
    automation_store = SQLiteAutomationStore(sqlite)
    automation = AutomationService(
        automation_store,
        clock=lambda: now[0],
    )
    store = SQLiteCalibrationCohortStore(sqlite)
    return _Harness(
        service=CalibrationCohortService(
            store,
            automation,
            config_registry,
            clock=lambda: now[0],
        ),
        automation=automation,
        store=store,
        automation_store=automation_store,
        config_registry=config_registry,
        source=source,
        now=now,
    )


def _member(
    target_id: str,
    *,
    success_policy: CalibrationSuccessPolicy = "procedure_success",
) -> CalibrationCohortMemberSpec:
    definition = CalibrationDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_DEFINITION_HASH,
        success_policy=success_policy,
    )
    target = CalibrationTargetRef(kind="qubit", id=target_id)
    procedure = ProcedureDefinitionRef(
        id="drag-calibration-procedure",
        version="1",
        fingerprint=_PROCEDURE_HASH,
    )
    return CalibrationCohortMemberSpec(
        member_id=f"drag-{target_id}",
        calibration_key=calibration_key(definition.id, target),
        definition=definition,
        target=target,
        procedure=procedure,
        intent={"target": target_id},
        input_fingerprint=_INPUT_HASH,
        freshness_fingerprint=calibration_freshness_fingerprint(
            definition=definition,
            target=target,
            procedure=procedure,
            input_fingerprint=_INPUT_HASH,
            dependencies=(),
        ),
        due_reasons=(CalibrationForcedDueReason(reason="test admission"),),
    )


def _command(
    cohort_id: str,
    *,
    source: CalibrationConfigSourceRef,
    snapshot: CalibrationStatusReceipt,
    members: tuple[CalibrationCohortMemberSpec, ...],
) -> CalibrationCohortCreateCommand:
    status = snapshot.snapshot
    return CalibrationCohortCreateCommand(
        cohort_id=cohort_id,
        spec=CalibrationCohortSpec(
            planner=members[0].definition,
            config_source=source,
            fanout_scope=status.fanout_scope,
            max_in_flight=4,
            observed_fanout_active_count=status.fanout_active_count,
            evaluated_at=status.observed_at,
            observations=status.statuses,
            members=members,
        ),
    )


def _status(
    harness: _Harness,
    members: tuple[CalibrationCohortMemberSpec, ...],
    *,
    scope: str = "calibration-workers",
) -> CalibrationStatusReceipt:
    return harness.service.status(
        CalibrationStatusQuery(
            calibration_keys=tuple(member.calibration_key for member in members),
            fanout_scope=scope,
        )
    )


def _close(
    harness: _Harness,
    member: CalibrationCohortMember,
    *,
    status: ProcedureCloseStatus,
) -> None:
    acquired = harness.automation.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=member.procedure_run_id,
            worker_id="test-worker",
            expected_run_revision=1,
        )
    )
    harness.now[0] += timedelta(seconds=1)
    harness.automation.close(
        ProcedureCloseCommand(
            procedure_run_id=member.procedure_run_id,
            lease_token=acquired.lease.lease_token,
            expected_run_revision=acquired.run.revision,
            status=status,
            reason=None if status == "succeeded" else "test failure",
        )
    )


def _attach_success_publication(
    harness: _Harness,
    pending: CalibrationSuccessRef,
) -> CalibrationSuccessRef:
    result_config = load_config().model_copy(update={"id": "calibration-result"})
    result = publish_config_revision(
        revision=ConfigRevision(
            source=DirectConfigRevisionSource(result_config),
            entry_id="calibration-result-entry",
            actor="test",
        ),
        unit_of_work=harness.config_registry.write_unit_of_work,
        expected_generation=pending.base_config_source.registry_generation,
    )
    activation = result.activation
    assert activation is not None
    command = ConfigPublishCommand(
        operation_id="publish:calibration-result",
        source=WireDirectConfigRevisionSource(config=result_config),
        actor="test",
        expected_generation=pending.base_config_source.registry_generation,
        entry_id=result.entry.id,
    )
    operation = ConfigPublishOperation(
        operation_id=command.operation_id,
        intent_hash=command.intent_hash,
        source_intent_hash=command.source_intent_hash,
        entry_id=command.entry_id,
        expected_generation=command.expected_generation,
        actor=command.actor,
        note=command.note,
        activation_generation=activation.generation,
        recorded_at=activation.recorded_at,
    )
    receipt = ConfigPublishReceipt(
        operation=operation,
        entry=result.entry,
        deltas=result.deltas,
        activation=activation,
    )
    result_source = CalibrationConfigSourceRef(
        entry_id=result.entry.id,
        config_ref=result.entry.config_ref,
        content_hash=result.entry.content_hash,
        registry_generation=activation.generation,
    )
    publication = CalibrationSuccessPublication(
        operation_id=operation.operation_id,
        source_intent_hash=operation.source_intent_hash,
        result_input_fingerprint=_RESULT_INPUT_HASH,
        result_freshness_fingerprint=calibration_freshness_fingerprint(
            definition=pending.attempt.definition,
            target=pending.attempt.target,
            procedure=pending.attempt.procedure,
            input_fingerprint=_RESULT_INPUT_HASH,
            dependencies=pending.attempt.dependencies,
        ),
        result_config_source=result_source,
        published_at=activation.recorded_at,
    )
    anchored = CalibrationSuccessRef(
        attempt=pending.attempt,
        base_config_source=pending.base_config_source,
        succeeded_at=pending.succeeded_at,
        publication=publication,
    )
    with harness.store.write_transaction() as connection:
        SQLiteConfigOperationStore(harness.store.sqlite).commit_in_transaction(
            connection,
            receipt,
        )
        harness.store.insert_success_publication_in_transaction(
            connection,
            anchored,
        )
    harness.now[0] = max(harness.now[0], activation.recorded_at)
    return anchored


def _move_to_active_state(
    harness: _Harness,
    member: CalibrationCohortMember,
    state: ProcedureRunState,
) -> None:
    if state == "ready":
        return
    acquired = harness.automation.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=member.procedure_run_id,
            worker_id="state-worker",
            expected_run_revision=1,
        )
    )
    if state == "leased":
        return
    if state == "waiting":
        harness.automation.wait(
            ProcedureWaitCommand(
                procedure_run_id=member.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=acquired.run.revision,
                condition=RunTerminalWait(run_id="dependency-run"),
            )
        )
        return
    assert state == "attention_required"
    harness.automation.require_run_attention(
        ProcedureRunAttentionCommand(
            procedure_run_id=member.procedure_run_id,
            lease_token=acquired.lease.lease_token,
            expected_run_revision=acquired.run.revision,
            reason="test attention",
        )
    )


def test_cohort_status_tracks_latest_attempt_and_prior_success(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    first_members = (_member("q0"), _member("q1"))
    command = _command(
        "drag-batch-1",
        source=harness.source,
        snapshot=_status(harness, first_members),
        members=first_members,
    )

    created = harness.service.create(command)
    assert tuple(member.index for member in created.members) == (0, 1)
    assert all(
        harness.automation.get(member.procedure_run_id).state == "ready"
        for member in created.members
    )
    assert harness.service.create(command) == created
    assert harness.service.list(CalibrationCohortListQuery()).items == (
        CalibrationCohortSummary.from_cohort(created.cohort),
    )

    first_member_page = harness.service.list_members(
        CalibrationCohortMemberListQuery(
            cohort_id=created.cohort.cohort_id,
            limit=1,
        )
    )
    assert first_member_page.items == (created.members[0],)
    assert first_member_page.next_cursor == 0
    assert harness.service.list_members(
        CalibrationCohortMemberListQuery(
            cohort_id=created.cohort.cohort_id,
            cursor=first_member_page.next_cursor,
            limit=1,
        )
    ).items == (created.members[1],)

    active = _status(harness, first_members)
    assert active.snapshot.fanout_active_count == 2
    assert all(
        item.latest_attempt is not None
        and item.latest_attempt.procedure_state == "ready"
        for item in active.snapshot.statuses
    )

    duplicate = _command(
        "drag-q0-concurrent",
        source=harness.source,
        snapshot=harness.service.status(
            CalibrationStatusQuery(
                calibration_keys=(first_members[0].calibration_key,),
                fanout_scope="calibration-workers",
            )
        ),
        members=(first_members[0],),
    )
    with pytest.raises(BackendConflict, match="active attempt"):
        harness.service.create(duplicate)

    _close(harness, created.members[0], status="succeeded")
    successful = harness.service.status(
        CalibrationStatusQuery(
            calibration_keys=(first_members[0].calibration_key,),
            fanout_scope="calibration-workers",
        )
    )
    [successful_status] = successful.snapshot.statuses
    assert successful_status.latest_success is not None
    assert (
        successful_status.latest_success.attempt.procedure_run_id
        == created.members[0].procedure_run_id
    )

    second = harness.service.create(
        _command(
            "drag-q0-retry",
            source=harness.source,
            snapshot=successful,
            members=(first_members[0],),
        )
    )
    _close(harness, second.members[0], status="failed")
    failed_latest = harness.service.status(
        CalibrationStatusQuery(
            calibration_keys=(first_members[0].calibration_key,),
            fanout_scope="calibration-workers",
        )
    ).snapshot.statuses[0]
    assert failed_latest.latest_attempt is not None
    assert failed_latest.latest_attempt.closure is not None
    assert failed_latest.latest_attempt.closure.status == "failed"
    assert failed_latest.latest_success == successful_status.latest_success

    later_config = load_config().model_copy(update={"id": "later-config"})
    publish_config_revision(
        revision=ConfigRevision(
            source=DirectConfigRevisionSource(later_config),
            entry_id="later-calibration-config",
            actor="test",
        ),
        unit_of_work=harness.config_registry.write_unit_of_work,
        expected_generation=1,
    )
    # Exact replay is resolved before changed config, status, and fanout checks.
    assert harness.service.create(command) == created


def test_success_publication_attaches_to_exact_member_and_status_projection(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    member = _member("q0", success_policy="published_result")
    created = harness.service.create(
        _command(
            "published-result",
            source=harness.source,
            snapshot=_status(harness, (member,)),
            members=(member,),
        )
    )
    _close(harness, created.members[0], status="succeeded")
    pending_status = _status(harness, (member,)).snapshot.statuses[0]
    pending = pending_status.latest_success
    assert pending is not None
    assert pending.base_config_source == harness.source
    assert pending.publication is None
    assert pending.is_effective is False

    anchored = _attach_success_publication(harness, pending)
    projected = _status(harness, (member,)).snapshot.statuses[0]

    assert projected.latest_success == anchored
    assert projected.latest_success is not None
    assert projected.latest_success.dependency_evidence.publication_operation_id == (
        "publish:calibration-result"
    )
    with harness.store.read_transaction() as connection:
        query, parameters = calibration_storage._status_rows_query(
            (member.calibration_key,)
        )
        plan = tuple(
            row["detail"]
            for row in connection.execute(
                f"EXPLAIN QUERY PLAN {query}",
                parameters,
            )
        )
    assert any(
        "SEARCH publications" in detail
        and "procedure_run_id=?" in detail
        and "LEFT-JOIN" in detail
        for detail in plan
    )
    assert not any("SCAN publications" in detail for detail in plan)

    with (
        pytest.raises(CalibrationCohortConflict, match="already has"),
        harness.store.write_transaction() as connection,
    ):
        harness.store.insert_success_publication_in_transaction(
            connection,
            anchored,
        )


def test_status_query_bounds_rows_to_latest_attempt_and_success(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    member = _member("q0")
    first = harness.service.create(
        _command(
            "history-success",
            source=harness.source,
            snapshot=_status(harness, (member,)),
            members=(member,),
        )
    )
    _close(harness, first.members[0], status="succeeded")
    first_success = _status(harness, (member,)).snapshot.statuses[0].latest_success
    assert first_success is not None

    latest_member = first.members[0]
    for index in range(64):
        admitted = harness.service.create(
            _command(
                f"history-failure-{index}",
                source=harness.source,
                snapshot=_status(harness, (member,)),
                members=(member,),
            )
        )
        latest_member = admitted.members[0]
        _close(harness, latest_member, status="failed")

    with harness.store.read_transaction() as connection:
        rows = harness.store._status_rows_in_transaction(
            connection,
            (member.calibration_key,),
        )
        query, parameters = calibration_storage._status_rows_query(
            (member.calibration_key,)
        )
        status_plan = tuple(
            row["detail"]
            for row in connection.execute(
                f"EXPLAIN QUERY PLAN {query}",
                parameters,
            )
        )
        active_plan = tuple(
            row["detail"]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN "
                + calibration_storage._ACTIVE_CALIBRATION_COUNT_SQL,
                ("calibration-workers",),
            )
        )
        projections = connection.execute(
            """
            SELECT members.sequence,
                   members.closure_status AS member_closure_status,
                   members.closed_at AS member_closed_at,
                   runs.closure_status AS run_closure_status,
                   runs.closed_at AS run_closed_at
            FROM calibration_cohort_members AS members
            JOIN procedure_runs AS runs
              ON runs.procedure_run_id = members.procedure_run_id
            WHERE members.calibration_key = ?
            ORDER BY members.sequence
            """,
            (member.calibration_key,),
        ).fetchall()

    assert len(rows) == 2
    assert tuple(row["closure_status"] for row in rows) == ("failed", "succeeded")
    assert any(
        "calibration_cohort_members_key_sequence" in detail for detail in status_plan
    )
    assert any(
        "calibration_cohort_members_success_key_sequence" in detail
        for detail in status_plan
    )
    assert any(
        "SEARCH members USING INTEGER PRIMARY KEY (rowid=?)" in detail
        for detail in status_plan
    )
    assert not any("SCAN members" in detail for detail in status_plan)
    assert any("procedure_runs_state_sequence" in detail for detail in active_plan)
    assert len(projections) == 65
    assert all(
        row["member_closure_status"] == row["run_closure_status"]
        and row["member_closed_at"] == row["run_closed_at"]
        for row in projections
    )
    sequences = tuple(row["sequence"] for row in projections)
    assert sequences == tuple(sorted(set(sequences)))
    status = _status(harness, (member,)).snapshot.statuses[0]
    assert status.latest_attempt is not None
    assert status.latest_attempt.attempt.procedure_run_id == (
        latest_member.procedure_run_id
    )
    assert status.latest_attempt.closure is not None
    assert status.latest_attempt.closure.status == "failed"
    assert status.latest_success == first_success


def test_status_clock_is_sampled_after_the_database_snapshot(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    member = _member("q0")
    created = harness.service.create(
        _command(
            "clock-order",
            source=harness.source,
            snapshot=_status(harness, (member,)),
            members=(member,),
        )
    )
    sampled_at = harness.now[0]

    def sample_while_run_closes() -> datetime:
        observed_at = harness.now[0]
        _close(harness, created.members[0], status="succeeded")
        return observed_at

    concurrent = CalibrationCohortService(
        harness.store,
        harness.automation,
        harness.config_registry,
        clock=sample_while_run_closes,
    )
    snapshot = concurrent.status(
        CalibrationStatusQuery(
            calibration_keys=(member.calibration_key,),
            fanout_scope="calibration-workers",
        )
    ).snapshot

    assert snapshot.observed_at == sampled_at
    assert snapshot.fanout_active_count == 1
    assert snapshot.statuses[0].latest_attempt is not None
    assert snapshot.statuses[0].latest_attempt.procedure_state == "ready"
    assert snapshot.statuses[0].latest_success is None
    closed = _status(harness, (member,)).snapshot.statuses[0]
    assert closed.latest_success is not None
    assert closed.latest_success.succeeded_at > snapshot.observed_at


@pytest.mark.parametrize(
    "state",
    ("ready", "leased", "waiting", "attention_required"),
)
def test_cohort_rejects_every_nonclosed_latest_attempt(
    tmp_path: Path,
    state: ProcedureRunState,
) -> None:
    harness = _harness(tmp_path)
    member = _member("q0")
    created = harness.service.create(
        _command(
            "active-attempt",
            source=harness.source,
            snapshot=_status(harness, (member,)),
            members=(member,),
        )
    )
    _move_to_active_state(harness, created.members[0], state)
    current = _status(harness, (member,))
    assert current.snapshot.statuses[0].latest_attempt is not None
    assert current.snapshot.statuses[0].latest_attempt.procedure_state == state

    with pytest.raises(BackendConflict, match="active attempt"):
        harness.service.create(
            _command(
                f"duplicate-{state}",
                source=harness.source,
                snapshot=current,
                members=(member,),
            )
        )

    assert len(harness.service.list(CalibrationCohortListQuery()).items) == 1
    assert len(harness.automation.list(ProcedureRunListQuery()).items) == 1


def test_cohort_create_rejects_stale_config_status_and_fanout(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    q0 = _member("q0")
    q1 = _member("q1")
    stale_q0_scope_a = _status(harness, (q0,), scope="scope-a")
    stale_q1_scope_b = _status(harness, (q1,), scope="scope-b")
    q1_scope_a = _status(harness, (q1,), scope="scope-a")
    admitted = harness.service.create(
        _command(
            "scope-a-q1",
            source=harness.source,
            snapshot=q1_scope_a,
            members=(q1,),
        )
    )

    with pytest.raises(BackendConflict, match="fanout activity changed"):
        harness.service.create(
            _command(
                "stale-fanout",
                source=harness.source,
                snapshot=stale_q0_scope_a,
                members=(q0,),
            )
        )
    with pytest.raises(BackendConflict, match="status observations changed"):
        harness.service.create(
            _command(
                "stale-status",
                source=harness.source,
                snapshot=stale_q1_scope_b,
                members=(q1,),
            )
        )

    forged_fields = (
        ("entry", {"entry_id": "forged-entry"}),
        ("ref", {"config_ref": "config-registry/configs/forged.config.json"}),
        ("hash", {"content_hash": "sha256:" + "9" * 64}),
    )
    for label, updates in forged_fields:
        forged_source = harness.source.model_copy(update=updates)
        with pytest.raises(BackendConflict, match="config registry source changed"):
            harness.service.create(
                _command(
                    f"forged-config-{label}",
                    source=forged_source,
                    snapshot=_status(harness, (q0,), scope="scope-c"),
                    members=(q0,),
                )
            )

    assert harness.service.list(CalibrationCohortListQuery()).items == (
        CalibrationCohortSummary.from_cohort(admitted.cohort),
    )
    assert len(harness.automation.list(ProcedureRunListQuery()).items) == 1


def test_cohort_create_rolls_back_every_member_run_on_member_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    members = (_member("q0"), _member("q1"))
    command = _command(
        "atomic-write",
        source=harness.source,
        snapshot=_status(harness, members),
        members=members,
    )
    insert = harness.store.insert_member_in_transaction

    def fail_second_member(
        connection: sqlite3.Connection,
        member: CalibrationCohortMember,
    ) -> None:
        if member.index == 1:
            raise CalibrationCohortConflict("injected member write failure")
        insert(connection, member)

    monkeypatch.setattr(
        harness.store,
        "insert_member_in_transaction",
        fail_second_member,
    )
    with pytest.raises(BackendConflict, match="injected member write failure"):
        harness.service.create(command)

    assert harness.automation.list(ProcedureRunListQuery()).items == ()
    assert harness.service.list(CalibrationCohortListQuery()).items == ()
    with pytest.raises(BackendNotFound):
        harness.service.get(CalibrationCohortGetQuery(cohort_id=command.cohort_id))


def test_cohort_refuses_to_adopt_a_preexisting_member_run(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    member = _member("q0")
    command = _command(
        "preexisting-run",
        source=harness.source,
        snapshot=_status(harness, (member,)),
        members=(member,),
    )
    request_key = calibration_cohort_member_request_key(command.cohort_id, member)
    existing = harness.automation.submit(
        ProcedureSubmitCommand(
            definition=member.procedure,
            request_key=request_key,
            intent=member.intent,
        )
    ).run

    with pytest.raises(BackendConflict, match="already has a durable run"):
        harness.service.create(command)

    assert harness.automation.list(ProcedureRunListQuery()).items == (existing,)
    assert harness.service.list(CalibrationCohortListQuery()).items == ()


def test_cohort_rolls_back_after_the_last_procedure_run_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    members = (_member("q0"), _member("q1"))
    command = _command(
        "procedure-insert-failure",
        source=harness.source,
        snapshot=_status(harness, members),
        members=members,
    )
    insert = harness.automation_store.insert_run_in_transaction
    calls = 0

    def fail_last_run(
        connection: sqlite3.Connection,
        run: ProcedureRun,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == len(members):
            raise AutomationConflict("injected procedure run write failure")
        insert(connection, run)

    monkeypatch.setattr(
        harness.automation_store,
        "insert_run_in_transaction",
        fail_last_run,
    )
    with pytest.raises(BackendConflict, match="injected procedure run write failure"):
        harness.service.create(command)

    assert harness.automation.list(ProcedureRunListQuery()).items == ()
    assert harness.service.list(CalibrationCohortListQuery()).items == ()


def test_calibration_cohort_http_sqlite_vertical_replays_after_restart(
    tmp_path: Path,
) -> None:
    member = _member("q0")
    cohort_id = "foo/members"
    encoded_id = quote(cohort_id, safe="")
    with (
        LocalDaemonRuntime(tmp_path, bootstrap_config=load_config()) as runtime,
        TestClient(runtime.app()) as client,
    ):
        active = runtime.application.config.get_active_config()
        source = CalibrationConfigSourceRef(
            selector="active",
            entry_id=active.entry.id,
            config_ref=active.entry.config_ref,
            content_hash=active.entry.content_hash,
            registry_generation=active.activation.generation,
        )
        status_response = client.post(
            "/api/v1/calibration-status/query",
            json=CalibrationStatusQuery(
                calibration_keys=(member.calibration_key,),
                fanout_scope="http-workers",
            ).model_dump(mode="json"),
        )
        assert status_response.status_code == 200
        status = CalibrationStatusReceipt.model_validate(status_response.json())
        command = _command(
            cohort_id,
            source=source,
            snapshot=status,
            members=(member,),
        )
        response = client.post(
            "/api/v1/calibration-cohorts",
            json=command.model_dump(mode="json"),
        )
        assert response.status_code == 201
        created = CalibrationCohortCreateReceipt.model_validate(response.json())

        get_response = client.get(f"/api/v1/calibration-cohorts/by-id/{encoded_id}")
        assert get_response.status_code == 200
        assert (
            CalibrationCohortGetReceipt.model_validate(get_response.json()).cohort
            == created.cohort
        )
        member_response = client.get(
            f"/api/v1/calibration-cohort-members/by-cohort/{encoded_id}"
        )
        assert member_response.status_code == 200
        assert member_response.json()["items"][0]["procedure_run_id"] == (
            created.members[0].procedure_run_id
        )

    with (
        LocalDaemonRuntime(tmp_path, bootstrap_config=load_config()) as restarted,
        TestClient(restarted.app()) as client,
    ):
        replay = client.post(
            "/api/v1/calibration-cohorts",
            json=command.model_dump(mode="json"),
        )
        assert replay.status_code == 201
        assert CalibrationCohortCreateReceipt.model_validate(replay.json()) == created
        procedures = ProcedureRunPage.model_validate(
            client.get("/api/v1/procedures").json()
        )
        assert len(procedures.items) == 1
        assert procedures.items[0].procedure_run_id == (
            created.members[0].procedure_run_id
        )
