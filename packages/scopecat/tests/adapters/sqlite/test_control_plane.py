from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest

from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ExecutorLeaseNotHeld,
    SchemaVersionError,
    SQLiteControlPlane,
)
from scopecat.control import (
    DurableEventInput,
    ResourceKey,
    RunAdmissionRecord,
)
from scopecat.records.run import RunOutcome

NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
CONFIG_HASH = f"sha256:{'1' * 64}"


def _store(path: Path) -> SQLiteControlPlane:
    store = SQLiteControlPlane(path)
    store.bootstrap()
    return store


def _admission(
    run_id: str,
    *resources: ResourceKey,
    admitted_at: datetime = NOW,
) -> RunAdmissionRecord:
    return RunAdmissionRecord(
        submission_id=f"submission:{run_id}",
        run_id=run_id,
        execution_mode="delegated",
        experiment_id=f"scratch:{run_id}",
        config_content_hash=CONFIG_HASH,
        plan_summary={"point_count": 3},
        resource_claims=resources,
        admitted_at=admitted_at,
    )


def _succeeded(run_id: str, *, at: datetime) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
        termination_reason="completed",
        finished_at=at,
    )


def test_bootstrap_is_idempotent_and_refuses_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    store = _store(path)

    store.bootstrap()

    assert store.schema_version() == 1
    with sqlite3.connect(path) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
        connection.execute("UPDATE control_schema SET version = 99")
    assert journal_mode == ("wal",)
    assert {
        "runs",
        "durable_events",
        "executor_leases",
        "resource_leases",
    } <= tables

    with pytest.raises(SchemaVersionError):
        store.bootstrap()


def test_run_admission_state_and_pagination(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    for offset in range(3):
        store.admit_run(
            _admission(
                f"run-{offset}",
                admitted_at=NOW + timedelta(seconds=offset),
            )
        )

    first = store.list_runs(limit=2)
    assert [run.run_id for run in first.items] == ["run-0", "run-1"]
    assert first.next_cursor == first.items[-1].sequence
    second = store.list_runs(limit=2, after=first.next_cursor)
    assert [run.run_id for run in second.items] == ["run-2"]
    assert second.next_cursor is None
    latest = store.list_runs(limit=2, latest=True)
    assert [run.run_id for run in latest.items] == ["run-1", "run-2"]
    assert latest.next_cursor is None
    assert latest.previous_cursor == latest.items[0].sequence
    older = store.list_runs(limit=2, before=latest.previous_cursor)
    assert [run.run_id for run in older.items] == ["run-0"]
    assert older.previous_cursor is None
    with pytest.raises(ValueError, match="do not accept a cursor"):
        store.list_runs(limit=2, after=1, latest=True)
    with pytest.raises(ValueError, match="either an after or before cursor"):
        store.list_runs(limit=2, after=1, before=2)

    retry = _admission("retry-run").model_copy(
        update={
            "submission_id": "submission:run-0",
            "experiment_id": "scratch:run-0",
            "admitted_at": NOW + timedelta(minutes=1),
        }
    )
    assert store.admit_run(retry) == store.get_run("run-0")
    assert store.get_run_by_submission_id("submission:run-0").run_id == "run-0"
    assert [event.kind for event in store.list_events(run_id="run-0").items] == [
        "run_admitted"
    ]

    with pytest.raises(ControlPlaneConflict):
        store.admit_run(
            retry.model_copy(update={"experiment_id": "different-experiment"})
        )


def test_executor_resources_and_terminal_state_commit_together(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    store.admit_run(
        _admission(
            "run-1",
            ResourceKey(kind="instrument", id="scope"),
            ResourceKey(kind="channel", id="scope:1"),
        )
    )
    executor = store.acquire_executor_lease(
        "run-1",
        executor_id="kernel-1",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    assert executor is not None
    claims = store.claim_run_resources(executor.token, at=NOW)
    assert claims.acquired
    assert len(claims.leases) == 2

    running = store.transition_run(
        "run-1",
        expected_state="accepted",
        state="running",
        executor_token=executor.token,
        at=NOW + timedelta(seconds=1),
    )
    assert running.state == "running"

    finished_at = NOW + timedelta(seconds=2)
    terminal = store.transition_run(
        "run-1",
        expected_state="running",
        state="terminal",
        outcome=_succeeded("run-1", at=finished_at),
        executor_token=executor.token,
        at=finished_at,
    )
    assert terminal.state == "terminal"
    assert terminal.outcome is not None
    assert store.list_resource_leases() == ()
    with pytest.raises(ExecutorLeaseNotHeld):
        store.append_event(
            DurableEventInput(run_id="run-1", kind="late_executor_event"),
            executor_token=executor.token,
        )


def test_durable_events_have_global_cursor_and_run_filter(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    store.admit_run(_admission("run-1"))
    for index in range(4):
        store.append_event(
            DurableEventInput(
                run_id="run-1",
                kind="measurement_chunk",
                payload={"index": index},
                occurred_at=NOW + timedelta(seconds=index),
            )
        )
    workspace_event = store.append_event(
        DurableEventInput(kind="config_activated", payload={"generation": 2})
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
    assert workspace_event.event_id > events[-1].event_id
    latest = store.list_events(run_id="run-1", limit=2, latest=True)
    assert [event.payload.get("index") for event in latest.items] == [2, 3]
    assert latest.next_cursor is None
    with pytest.raises(ValueError, match="after cursor"):
        store.list_events(limit=2, after=1, latest=True)


def test_resource_claims_are_all_or_none(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    shared = ResourceKey(kind="instrument", id="scope")
    store.admit_run(_admission("run-a", shared, ResourceKey(kind="channel", id="a")))
    store.admit_run(_admission("run-b", shared, ResourceKey(kind="channel", id="b")))
    executor_a = store.acquire_executor_lease(
        "run-a",
        executor_id="a",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    executor_b = store.acquire_executor_lease(
        "run-b",
        executor_id="b",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    assert executor_a is not None
    assert executor_b is not None

    assert store.claim_run_resources(executor_a.token, at=NOW).acquired
    rejected = store.claim_run_resources(executor_b.token, at=NOW)

    assert not rejected.acquired
    assert [conflict.resource for conflict in rejected.conflicts] == [shared]
    leases = store.list_resource_leases()
    assert {lease.resource.id for lease in leases} == {"scope", "a"}
    assert {lease.run_id for lease in leases} == {"run-a"}


def test_concurrent_resource_claim_has_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "control.sqlite3"
    store = _store(path)
    shared = ResourceKey(kind="instrument", id="scope")
    store.admit_run(_admission("run-a", shared))
    store.admit_run(_admission("run-b", shared))
    executor_a = store.acquire_executor_lease(
        "run-a",
        executor_id="a",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    executor_b = store.acquire_executor_lease(
        "run-b",
        executor_id="b",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    assert executor_a is not None
    assert executor_b is not None
    barrier = Barrier(2)

    def claim(token: str) -> bool:
        peer = SQLiteControlPlane(path)
        barrier.wait()
        return peer.claim_run_resources(token, at=NOW).acquired

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (executor_a.token, executor_b.token)))

    assert sorted(results) == [False, True]
    assert len(store.list_resource_leases()) == 1


def test_expired_running_executor_quarantines_resources(tmp_path: Path) -> None:
    store = _store(tmp_path / "control.sqlite3")
    shared = ResourceKey(kind="instrument", id="scope")
    store.admit_run(_admission("lost", shared))
    store.admit_run(_admission("waiting", shared))
    lost = store.acquire_executor_lease(
        "lost",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW,
    )
    waiting = store.acquire_executor_lease(
        "waiting",
        executor_id="daemon",
        ttl=timedelta(seconds=30),
        at=NOW,
    )
    assert lost is not None
    assert waiting is not None
    assert store.claim_run_resources(lost.token, at=NOW).acquired
    store.transition_run(
        "lost",
        expected_state="accepted",
        state="running",
        executor_token=lost.token,
        at=NOW + timedelta(seconds=1),
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
    quarantined = store.list_resource_leases()
    assert len(quarantined) == 1
    assert quarantined[0].status == "quarantined"
    rejected = store.claim_run_resources(
        waiting.token,
        at=NOW + timedelta(seconds=11),
    )
    assert not rejected.acquired
    assert rejected.conflicts[0].status == "quarantined"

    assert store.release_run_resources("lost") == 1
    assert store.claim_run_resources(
        waiting.token,
        at=NOW + timedelta(seconds=12),
    ).acquired


def test_renewal_extends_resource_expiry_and_generation_fences_old_token(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "control.sqlite3")
    store.admit_run(_admission("run-1", ResourceKey(kind="instrument", id="scope")))
    first = store.acquire_executor_lease(
        "run-1",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW,
    )
    assert first is not None
    assert store.claim_run_resources(first.token, at=NOW).acquired

    renewed = store.renew_executor_lease(
        first.token,
        ttl=timedelta(seconds=20),
        at=NOW + timedelta(seconds=5),
    )
    assert store.list_resource_leases()[0].expires_at == renewed.expires_at
    assert "executor_lease_renewed" in {
        event.kind for event in store.list_events(run_id="run-1").items
    }
    assert store.release_executor_lease(first.token)

    second = store.acquire_executor_lease(
        "run-1",
        executor_id="kernel",
        ttl=timedelta(seconds=10),
        at=NOW + timedelta(seconds=6),
    )
    assert second is not None
    assert second.generation == first.generation + 1
    with pytest.raises(ExecutorLeaseNotHeld):
        store.append_event(
            DurableEventInput(
                run_id="run-1",
                kind="stale",
                occurred_at=NOW + timedelta(seconds=6),
            ),
            executor_token=first.token,
        )
