from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ExecutorLeaseNotHeld,
    InstrumentSessionLeaseNotHeld,
    SQLiteControlPlane,
    SQLiteProjectStore,
)
from scopecat.control.models import (
    ControlRun,
    DurableEvent,
    DurableEventInput,
    ExecutorLease,
    ResourceKey,
    ResourceLease,
    RunAdmissionRecord,
    RunPlanSummary,
)

NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
SUBMISSION_HASH = "1" * 64


def _store(path: Path) -> SQLiteControlPlane:
    SQLiteProjectStore(path, path.parent / "objects").bootstrap()
    return SQLiteControlPlane(path)


def _admission(
    run_id: str,
    *resources: ResourceKey,
    admitted_at: datetime = NOW,
) -> RunAdmissionRecord:
    return RunAdmissionRecord(
        submission_id=f"submission:{run_id}",
        submission_content_hash=SUBMISSION_HASH,
        run_id=run_id,
        plan=RunPlanSummary(
            experiment_id=f"scratch:{run_id}",
            experiment_kind="scratch",
            point_count=3,
            run_resource_claims=resources,
            host_instrument_order=tuple(
                resource.id for resource in resources if resource.kind == "instrument"
            ),
        ),
        admitted_at=admitted_at,
    )


def _admit(
    store: SQLiteControlPlane,
    admission: RunAdmissionRecord,
) -> ControlRun:
    with store.transaction() as connection:
        return store.admit_run_in_transaction(connection, admission)


def _start(
    store: SQLiteControlPlane,
    run_id: str,
    *,
    executor_id: str,
    ttl: timedelta | None = None,
    at: datetime = NOW,
) -> ExecutorLease:
    with store.transaction() as connection:
        return store.start_execution_in_transaction(
            connection,
            run_id,
            executor_id=executor_id,
            ttl=ttl or timedelta(seconds=30),
            at=at,
        )


def _close(
    store: SQLiteControlPlane,
    run_id: str,
    *,
    executor_token: str | None = None,
    at: datetime,
) -> ControlRun:
    with store.transaction() as connection:
        return store.close_run_in_transaction(
            connection,
            run_id,
            executor_token=executor_token,
            at=at,
        )


def _append_event(
    store: SQLiteControlPlane,
    event: DurableEventInput,
    *,
    executor_token: str | None = None,
) -> DurableEvent:
    if executor_token is not None:
        assert event.run_id is not None
        with store.fenced_transaction(
            event.run_id,
            token=executor_token,
            at=event.occurred_at,
        ) as connection:
            return store.append_event_in_transaction(connection, event)
    with store.transaction() as connection:
        return store.append_event_in_transaction(connection, event)


def _resource_leases(store: SQLiteControlPlane) -> tuple[ResourceLease, ...]:
    with store.transaction() as connection:
        return store.list_resource_leases_in_transaction(connection)


def _release_run_resources(store: SQLiteControlPlane, run_id: str) -> int:
    with store.transaction() as connection:
        return store.release_run_resources_in_transaction(connection, run_id)


def _executor_lease(
    store: SQLiteControlPlane,
    run_id: str,
) -> ExecutorLease | None:
    with store.transaction() as connection:
        return store.executor_lease_for_run_in_transaction(connection, run_id)


def test_run_admission_state_and_pagination(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    for offset in range(3):
        _admit(
            store,
            _admission(
                f"run-{offset}",
                admitted_at=NOW + timedelta(seconds=offset),
            ),
        )

    first = store.list_runs(limit=2)
    assert [run.run_id for run in first.items] == ["run-2", "run-1"]
    assert first.next_cursor == first.items[-1].sequence
    second = store.list_runs(limit=2, before=first.next_cursor)
    assert [run.run_id for run in second.items] == ["run-0"]
    assert second.next_cursor is None

    retry = _admission("retry-run").model_copy(
        update={
            "submission_id": "submission:run-0",
            "plan": RunPlanSummary(
                experiment_id="scratch:run-0",
                experiment_kind="scratch",
                point_count=3,
            ),
            "admitted_at": NOW + timedelta(minutes=1),
        }
    )
    assert _admit(store, retry) == store.get_run("run-0")
    assert second.items[0].admission.submission_id == "submission:run-0"
    assert [event.kind for event in store.list_events(run_id="run-0").items] == [
        "run_admitted"
    ]

    with pytest.raises(ControlPlaneConflict):
        _admit(
            store,
            retry.model_copy(update={"submission_content_hash": "2" * 64}),
        )


def test_executor_resources_and_scheduler_close_commit_together(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    _admit(
        store,
        _admission(
            "run-1",
            ResourceKey(kind="instrument", id="scope"),
            ResourceKey(kind="target", id="controller"),
        ),
    )
    executor = _start(
        store,
        "run-1",
        executor_id="kernel-1",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    assert store.get_run("run-1").state == "leased"
    assert len(_resource_leases(store)) == 2

    finished_at = NOW + timedelta(seconds=2)
    closed = _close(
        store,
        "run-1",
        executor_token=executor.token,
        at=finished_at,
    )
    assert closed.state == "closed"
    assert _resource_leases(store) == ()
    with pytest.raises(ExecutorLeaseNotHeld):
        _append_event(
            store,
            DurableEventInput(run_id="run-1", kind="late_executor_event"),
            executor_token=executor.token,
        )


def test_durable_events_have_global_cursor_and_run_filter(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    _admit(store, _admission("run-1"))
    for index in range(4):
        _append_event(
            store,
            DurableEventInput(
                run_id="run-1",
                kind="measurement_chunk",
                payload={"index": index},
                occurred_at=NOW + timedelta(seconds=index),
            ),
        )
    later_event = _append_event(
        store, DurableEventInput(kind="config_activated", payload={"generation": 2})
    )

    first = store.list_events(run_id="run-1", limit=2)
    second = store.list_events(
        run_id="run-1",
        limit=10,
        after=first.next_cursor,
    )
    events = (*first.items, *second.items)
    assert [event.event_id for event in events] == sorted(
        event.event_id for event in events
    )
    assert [event.kind for event in events] == [
        "run_admitted",
        "measurement_chunk",
        "measurement_chunk",
        "measurement_chunk",
        "measurement_chunk",
    ]
    assert later_event.event_id > events[-1].event_id
    latest = store.list_events(run_id="run-1", limit=2, latest=True)
    assert [event.payload.get("index") for event in latest.items] == [2, 3]
    assert latest.next_cursor is None
    with pytest.raises(ValueError, match="after cursor"):
        store.list_events(limit=2, after=1, latest=True)


def test_resource_claims_are_all_or_none(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    shared = ResourceKey(kind="instrument", id="scope")
    _admit(
        store,
        _admission("run-a", shared, ResourceKey(kind="target", id="a")),
    )
    _admit(
        store,
        _admission("run-b", shared, ResourceKey(kind="target", id="b")),
    )
    _start(
        store,
        "run-a",
        executor_id="a",
    )

    with pytest.raises(ControlPlaneConflict, match="resources are busy"):
        _start(store, "run-b", executor_id="b")
    leases = _resource_leases(store)
    assert {lease.resource.id for lease in leases} == {"scope", "a"}
    assert {(lease.owner_kind, lease.owner_id) for lease in leases} == {
        ("run", "run-a")
    }
    assert _executor_lease(store, "run-b") is None
    assert store.get_run("run-b").state == "queued"


def test_concurrent_resource_claim_has_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    store = _store(path)
    shared = ResourceKey(kind="instrument", id="scope")
    _admit(store, _admission("run-a", shared))
    _admit(store, _admission("run-b", shared))
    barrier = Barrier(2)

    def start(run_id: str) -> bool:
        peer = SQLiteControlPlane(path)
        barrier.wait()
        try:
            _start(peer, run_id, executor_id=run_id)
        except ControlPlaneConflict:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, ("run-a", "run-b")))

    assert sorted(results) == [False, True]
    assert len(_resource_leases(store)) == 1


def test_expired_leased_executor_quarantines_resources(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    shared = ResourceKey(kind="instrument", id="scope")
    _admit(store, _admission("lost", shared))
    _admit(store, _admission("waiting", shared))
    _start(
        store,
        "lost",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW,
    )

    expired = store.expire_executor_leases(at=NOW + timedelta(seconds=11))

    assert expired == ("lost",)
    run = store.get_run("lost")
    assert run.state == "attention_required"
    assert run.attention_reason == "executor_lease_expired"
    event_kinds = {event.kind for event in store.list_events(run_id="lost").items}
    assert {
        "executor_lease_granted",
        "resources_claimed",
        "resources_quarantined",
        "executor_lease_lost",
    } <= event_kinds
    quarantined = _resource_leases(store)
    assert len(quarantined) == 1
    assert quarantined[0].status == "quarantined"
    with pytest.raises(ControlPlaneConflict, match="resources are busy"):
        _start(
            store,
            "waiting",
            executor_id="daemon",
            at=NOW + timedelta(seconds=11),
        )

    assert _release_run_resources(store, "lost") == 1
    waiting = _start(
        store,
        "waiting",
        executor_id="daemon",
        at=NOW + timedelta(seconds=12),
    )
    assert waiting.run_id == "waiting"
    assert store.get_run("lost").state == "attention_required"


def test_renewal_extends_resource_expiry_and_close_fences_token(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    _admit(
        store,
        _admission("run-1", ResourceKey(kind="instrument", id="scope")),
    )
    first = _start(
        store,
        "run-1",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW,
    )
    events_before_renewal = store.list_events(run_id="run-1").items

    with pytest.raises(ExecutorLeaseNotHeld, match="belongs to another run"):
        store.renew_executor_lease(
            "run-2",
            first.token,
            ttl=timedelta(seconds=20),
            at=NOW + timedelta(seconds=5),
        )
    renewed = store.renew_executor_lease(
        "run-1",
        first.token,
        ttl=timedelta(seconds=20),
        at=NOW + timedelta(seconds=5),
    )
    assert _resource_leases(store)[0].expires_at == renewed.expires_at
    assert renewed.renewed_at == NOW + timedelta(seconds=5)
    assert store.list_events(run_id="run-1").items == events_before_renewal
    _close(
        store,
        "run-1",
        executor_token=first.token,
        at=NOW + timedelta(seconds=6),
    )
    with pytest.raises(ExecutorLeaseNotHeld):
        _append_event(
            store,
            DurableEventInput(
                run_id="run-1",
                kind="stale",
                occurred_at=NOW + timedelta(seconds=6),
            ),
            executor_token=first.token,
        )


def test_uncertain_executor_io_fences_exact_token_and_quarantines_resources(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    _admit(
        store,
        _admission("run-1", ResourceKey(kind="instrument", id="scope")),
    )
    lease = _start(
        store,
        "run-1",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW,
    )

    with pytest.raises(ExecutorLeaseNotHeld):
        store.mark_executor_unknown(
            "run-1",
            token=f"{lease.token}-stale",
            reason="instrument_apply_unknown",
            at=NOW + timedelta(seconds=1),
        )
    lost = store.mark_executor_unknown(
        "run-1",
        token=lease.token,
        reason="instrument_apply_unknown",
        at=NOW + timedelta(seconds=1),
    )

    assert lost.state == "attention_required"
    assert lost.attention_reason == "instrument_apply_unknown"
    assert _executor_lease(store, "run-1") is None
    [resource] = _resource_leases(store)
    assert resource.status == "quarantined"
    assert resource.owner_token is None


def test_instrument_session_retry_heartbeat_and_loss_quarantine(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    first = store.open_instrument_session(
        operation_id="open-1",
        actor="alice",
        config_entry_id="baseline",
        config_content_hash=f"sha256:{'a' * 64}",
        instrument_ids=("scope",),
        ttl=timedelta(seconds=10),
        at=NOW,
    )
    retry = store.open_instrument_session(
        operation_id="open-1",
        actor="alice",
        config_entry_id="baseline",
        config_content_hash=f"sha256:{'a' * 64}",
        instrument_ids=("scope",),
        ttl=timedelta(seconds=10),
        at=NOW + timedelta(seconds=1),
    )

    assert retry == first
    with pytest.raises(ControlPlaneConflict, match="different content"):
        store.open_instrument_session(
            operation_id="open-1",
            actor="bob",
            config_entry_id="baseline",
            config_content_hash=f"sha256:{'a' * 64}",
            instrument_ids=("scope",),
            ttl=timedelta(seconds=10),
            at=NOW + timedelta(seconds=1),
        )

    renewed = store.renew_instrument_session(
        first.session_id,
        first.token or "",
        ttl=timedelta(seconds=20),
        at=NOW + timedelta(seconds=5),
    )
    assert _resource_leases(store)[0].expires_at == renewed.expires_at
    assert store.expire_instrument_sessions(at=NOW + timedelta(seconds=24)) == ()
    assert store.expire_instrument_sessions(at=NOW + timedelta(seconds=26)) == (
        first.session_id,
    )

    lost = store.get_instrument_session(first.session_id)
    [resource] = _resource_leases(store)
    assert lost.state == "attention_required"
    assert lost.attention_reason == "instrument_session_lease_expired"
    assert resource.owner_kind == "instrument_session"
    assert resource.owner_id == first.session_id
    assert resource.status == "quarantined"
    with pytest.raises(InstrumentSessionLeaseNotHeld):
        store.validate_instrument_session(
            first.session_id,
            token=first.token or "",
            at=NOW + timedelta(seconds=26),
        )

    _closed, released = store.resolve_instrument_session_attention(
        first.session_id,
        at=NOW + timedelta(seconds=27),
    )
    assert released == 1
    assert _resource_leases(store) == ()


def test_instrument_session_cannot_claim_a_run_owned_resource(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    resource = ResourceKey(kind="instrument", id="scope")
    _admit(store, _admission("run-1", resource))
    _start(store, "run-1", executor_id="kernel")

    with pytest.raises(ControlPlaneConflict, match="resources are busy"):
        store.open_instrument_session(
            operation_id="open-1",
            actor="alice",
            config_entry_id="baseline",
            config_content_hash=f"sha256:{'a' * 64}",
            instrument_ids=("scope",),
            ttl=timedelta(seconds=10),
            at=NOW,
        )
