"""SQLite control plane for a daemon-owned workspace."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from scopecat.adapters.sqlite.schema import SCHEMA_SQL, SCHEMA_VERSION
from scopecat.control.models import (
    ControlRun,
    ControlRunState,
    DurableEvent,
    DurableEventInput,
    EventPage,
    ExecutorLease,
    ResourceClaimConflict,
    ResourceClaimResult,
    ResourceKey,
    ResourceLease,
    RunAdmissionRecord,
    RunPage,
)
from scopecat.records.run import RunOutcome

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_ALLOWED_TRANSITIONS: dict[ControlRunState, frozenset[ControlRunState]] = {
    "accepted": frozenset({"running", "terminal"}),
    "running": frozenset({"terminal", "attention_required"}),
    "attention_required": frozenset({"accepted", "terminal"}),
    "terminal": frozenset(),
}


class ControlPlaneError(RuntimeError):
    """Base failure from the SQLite control plane."""


class SchemaVersionError(ControlPlaneError):
    """The database belongs to an unsupported control-plane schema."""


class ControlPlaneNotFound(ControlPlaneError):
    """A requested control-plane record does not exist."""


class ControlPlaneConflict(ControlPlaneError):
    """A compare-and-set precondition or lifecycle invariant failed."""


class ExecutorLeaseNotHeld(ControlPlaneConflict):
    """The executor fencing token is absent, stale, or expired."""


class SQLiteControlPlane:
    """Transactional scheduler state and globally ordered durable events."""

    def __init__(self, path: str | Path, *, busy_timeout: timedelta | None = None):
        self.path = Path(path)
        self._busy_timeout_ms = int(
            (busy_timeout or timedelta(seconds=5)).total_seconds() * 1000
        )

    def bootstrap(self) -> None:
        """Create the current schema, refusing implicit schema migration."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA_SQL)
            row = _one(
                connection.execute(
                    "SELECT version FROM control_schema WHERE singleton = 1"
                )
            )
        if row is None or _integer(row, "version") != SCHEMA_VERSION:
            version = None if row is None else _integer(row, "version")
            raise SchemaVersionError(
                f"unsupported control-plane schema version: {version}"
            )

    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            row = _one(
                connection.execute(
                    "SELECT version FROM control_schema WHERE singleton = 1"
                )
            )
        if row is None:
            raise SchemaVersionError("control-plane schema is not bootstrapped")
        return _integer(row, "version")

    def admit_run(self, admission: RunAdmissionRecord) -> ControlRun:
        """Publish the admission, requirements, and first event atomically."""

        with self._transaction() as connection:
            return self.admit_run_in_transaction(connection, admission)

    def admit_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        admission: RunAdmissionRecord,
    ) -> ControlRun:
        """Publish control admission through an existing daemon transaction."""

        admitted_at = _timestamp(admission.admitted_at)
        try:
            cursor = connection.execute(
                """
                INSERT INTO runs(
                    submission_id, run_id, state, state_version, admitted_at,
                    updated_at, admission_json, outcome_json, attention_reason
                )
                VALUES (?, ?, 'accepted', 1, ?, ?, ?, NULL, NULL)
                """,
                (
                    admission.submission_id,
                    admission.run_id,
                    admitted_at,
                    admitted_at,
                    admission.model_dump_json(),
                ),
            )
        except sqlite3.IntegrityError as error:
            existing = self._find_admission_conflict(connection, admission)
            if existing is not None:
                return existing
            raise ControlPlaneConflict(
                "run id or submission id is already admitted"
            ) from error
        connection.executemany(
            """
            INSERT INTO run_resource_requirements(
                run_id, resource_kind, resource_id
            )
            VALUES (?, ?, ?)
            """,
            [
                (admission.run_id, resource.kind, resource.id)
                for resource in admission.resource_claims
            ],
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=admission.run_id,
                kind="run_admitted",
                payload={
                    "execution_mode": admission.execution_mode,
                    "experiment_id": admission.experiment_id,
                    "submission_id": admission.submission_id,
                    "state_version": 1,
                },
                occurred_at=admission.admitted_at,
            ),
        )
        row = _one(
            connection.execute(
                "SELECT * FROM runs WHERE sequence = ?",
                (cast("int", cursor.lastrowid),),
            )
        )
        assert row is not None  # noqa: S101
        return _run(row)

    def get_run(self, run_id: str) -> ControlRun:
        with closing(self._connect()) as connection:
            return self.get_run_in_transaction(connection, run_id)

    def get_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> ControlRun:
        """Read a run through an existing daemon transaction."""

        return _run(self._require_run(connection, run_id))

    def get_run_by_submission_id(self, submission_id: str) -> ControlRun:
        with closing(self._connect()) as connection:
            row = _one(
                connection.execute(
                    "SELECT * FROM runs WHERE submission_id = ?",
                    (submission_id,),
                )
            )
        if row is None:
            raise ControlPlaneNotFound(f"submission was not found: {submission_id}")
        return _run(row)

    def list_runs(
        self,
        *,
        limit: int = 50,
        after: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunPage:
        """Return a keyset page in immutable admission order."""

        _page_size(limit)
        if latest and after is not None:
            raise ValueError("latest run snapshots do not accept an after cursor")
        cursor = after or 0
        with closing(self._connect()) as connection:
            if latest and state is None:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM runs
                        ORDER BY sequence DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                )
            elif latest:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM runs
                        WHERE state = ?
                        ORDER BY sequence DESC
                        LIMIT ?
                        """,
                        (state, limit),
                    )
                )
            elif state is None:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM runs
                        WHERE sequence > ?
                        ORDER BY sequence
                        LIMIT ?
                        """,
                        (cursor, limit + 1),
                    )
                )
            else:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM runs
                        WHERE sequence > ? AND state = ?
                        ORDER BY sequence
                        LIMIT ?
                        """,
                        (cursor, state, limit + 1),
                    )
                )
        if latest:
            rows.reverse()
        items = tuple(_run(row) for row in rows[:limit])
        next_cursor = None if latest or len(rows) <= limit else items[-1].sequence
        return RunPage(items=items, next_cursor=next_cursor)

    def transition_run(
        self,
        run_id: str,
        *,
        expected_state: ControlRunState,
        state: ControlRunState,
        outcome: RunOutcome | None = None,
        attention_reason: str | None = None,
        executor_token: str | None = None,
        at: datetime | None = None,
    ) -> ControlRun:
        """Compare-and-set run state and its replay event."""

        with self._transaction() as connection:
            return self.transition_run_in_transaction(
                connection,
                run_id,
                expected_state=expected_state,
                state=state,
                outcome=outcome,
                attention_reason=attention_reason,
                executor_token=executor_token,
                at=at,
            )

    def transition_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        expected_state: ControlRunState,
        state: ControlRunState,
        outcome: RunOutcome | None = None,
        attention_reason: str | None = None,
        executor_token: str | None = None,
        at: datetime | None = None,
    ) -> ControlRun:
        """Apply a lifecycle transition inside an existing write transaction."""

        changed_at = at or datetime.now(tz=UTC)
        current = _run(self._require_run(connection, run_id))
        if current.state != expected_state:
            raise ControlPlaneConflict(
                f"run {run_id} is {current.state}, expected {expected_state}"
            )
        if state not in _ALLOWED_TRANSITIONS[current.state]:
            raise ControlPlaneConflict(
                f"invalid run state transition: {current.state} -> {state}"
            )
        lease = self._transition_lease(
            connection,
            current,
            state,
            executor_token,
            changed_at,
        )
        updated = ControlRun.model_validate(
            {
                **current.model_dump(),
                "state": state,
                "state_version": current.state_version + 1,
                "updated_at": changed_at,
                "outcome": outcome,
                "attention_reason": attention_reason,
            }
        )
        connection.execute(
            """
            UPDATE runs SET
                state = ?, state_version = ?, updated_at = ?,
                outcome_json = ?, attention_reason = ?
            WHERE run_id = ?
            """,
            (
                state,
                updated.state_version,
                _timestamp(changed_at),
                outcome.model_dump_json() if outcome is not None else None,
                attention_reason,
                run_id,
            ),
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind="run_state_changed",
                payload={
                    "from": current.state,
                    "to": state,
                    "state_version": updated.state_version,
                },
                occurred_at=changed_at,
            ),
        )
        if state == "attention_required":
            assert lease is not None  # noqa: S101
            quarantined = self._quarantine(connection, lease.token)
            connection.execute(
                "DELETE FROM executor_leases WHERE token = ?", (lease.token,)
            )
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="resources_quarantined",
                    payload={"count": quarantined},
                    occurred_at=changed_at,
                ),
            )
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="executor_lease_lost",
                    payload={
                        "executor_id": lease.executor_id,
                        "generation": lease.generation,
                    },
                    occurred_at=changed_at,
                ),
            )
        elif state == "terminal":
            released = connection.execute(
                "DELETE FROM resource_leases WHERE run_id = ?", (run_id,)
            ).rowcount
            connection.execute(
                "DELETE FROM executor_leases WHERE run_id = ?", (run_id,)
            )
            if released:
                self._insert_event(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="resources_released",
                        payload={"count": released},
                        occurred_at=changed_at,
                    ),
                )
        return _run(self._require_run(connection, run_id))

    def append_event(
        self,
        event: DurableEventInput,
        *,
        executor_token: str | None = None,
    ) -> DurableEvent:
        """Append an event, optionally fenced to the live run executor."""

        with self._transaction() as connection:
            if executor_token is not None:
                if event.run_id is None:
                    msg = "executor-fenced event must belong to a run"
                    raise ValueError(msg)
                self._live_executor(
                    connection,
                    executor_token,
                    at=event.occurred_at,
                    run_id=event.run_id,
                )
            return self.append_event_in_transaction(connection, event)

    def append_event_in_transaction(
        self,
        connection: sqlite3.Connection,
        event: DurableEventInput,
    ) -> DurableEvent:
        """Append a replay event inside the caller's write transaction."""

        if event.run_id is not None:
            self._require_run(connection, event.run_id)
        return self._insert_event(connection, event)

    def list_events(
        self,
        *,
        limit: int = 100,
        after: int | None = None,
        run_id: str | None = None,
        latest: bool = False,
    ) -> EventPage:
        """Return a page in the single global replay order."""

        _page_size(limit)
        if latest and after is not None:
            raise ValueError("latest event snapshots do not accept an after cursor")
        cursor = after or 0
        with closing(self._connect()) as connection:
            if latest and run_id is None:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM durable_events
                        ORDER BY event_id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                )
            elif latest:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM durable_events
                        WHERE run_id = ?
                        ORDER BY event_id DESC
                        LIMIT ?
                        """,
                        (run_id, limit),
                    )
                )
            elif run_id is None:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM durable_events
                        WHERE event_id > ?
                        ORDER BY event_id
                        LIMIT ?
                        """,
                        (cursor, limit + 1),
                    )
                )
            else:
                rows = _all(
                    connection.execute(
                        """
                        SELECT * FROM durable_events
                        WHERE event_id > ? AND run_id = ?
                        ORDER BY event_id
                        LIMIT ?
                        """,
                        (cursor, run_id, limit + 1),
                    )
                )
        if latest:
            rows.reverse()
        items = tuple(_event(row) for row in rows[:limit])
        next_cursor = None if latest or len(rows) <= limit else items[-1].event_id
        return EventPage(items=items, next_cursor=next_cursor)

    def acquire_executor_lease(
        self,
        run_id: str,
        *,
        executor_id: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> ExecutorLease | None:
        """Acquire a new fencing generation, or return ``None`` if held."""

        _ttl(ttl)
        acquired_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            if self._expire_one(connection, run_id, acquired_at):
                return None
            run = _run(self._require_run(connection, run_id))
            if run.state != "accepted":
                raise ControlPlaneConflict(
                    f"executor can only acquire an accepted run, got {run.state}"
                )
            held = _one(
                connection.execute(
                    "SELECT 1 AS held FROM executor_leases WHERE run_id = ?",
                    (run_id,),
                )
            )
            if held is not None:
                return None
            connection.execute(
                """
                INSERT INTO executor_generations(run_id, generation) VALUES (?, 1)
                ON CONFLICT(run_id)
                DO UPDATE SET generation = generation + 1
                """,
                (run_id,),
            )
            generation_row = _one(
                connection.execute(
                    "SELECT generation FROM executor_generations WHERE run_id = ?",
                    (run_id,),
                )
            )
            assert generation_row is not None  # noqa: S101
            generation = _integer(generation_row, "generation")
            token = f"{generation}:{uuid4().hex}"
            expires_at = acquired_at + ttl
            connection.execute(
                """
                INSERT INTO executor_leases(
                    run_id, executor_id, token, generation,
                    acquired_at, renewed_at, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    executor_id,
                    token,
                    generation,
                    _timestamp(acquired_at),
                    _timestamp(acquired_at),
                    _timestamp(expires_at),
                ),
            )
            row = _one(
                connection.execute(
                    "SELECT * FROM executor_leases WHERE token = ?", (token,)
                )
            )
            assert row is not None  # noqa: S101
            lease = _executor(row)
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="executor_lease_granted",
                    payload={
                        "executor_id": executor_id,
                        "generation": generation,
                        "expires_at": _timestamp(expires_at),
                    },
                    occurred_at=acquired_at,
                ),
            )
            return lease

    def start_execution_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        executor_id: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Lease every declared resource and enter running atomically."""

        _ttl(ttl)
        started_at = at or datetime.now(tz=UTC)
        self._expire_one(connection, run_id, started_at)
        run = _run(self._require_run(connection, run_id))
        if run.state != "accepted":
            raise ControlPlaneConflict(
                f"executor can only start an accepted run, got {run.state}"
            )
        requirements = self._requirements(connection, run_id)
        conflicts: list[ResourceClaimConflict] = []
        for resource in requirements:
            row = _one(
                connection.execute(
                    """
                    SELECT * FROM resource_leases
                    WHERE resource_kind = ? AND resource_id = ?
                    """,
                    (resource.kind, resource.id),
                )
            )
            if row is None:
                continue
            held = _resource_lease(row)
            conflicts.append(
                ResourceClaimConflict(
                    resource=resource,
                    owner_run_id=held.run_id,
                    status=held.status,
                )
            )
        if conflicts:
            owners = ", ".join(
                f"{item.resource.kind}:{item.resource.id}" for item in conflicts
            )
            raise ControlPlaneConflict(f"run resources are busy: {owners}")

        connection.execute(
            """
            INSERT INTO executor_generations(run_id, generation) VALUES (?, 1)
            ON CONFLICT(run_id)
            DO UPDATE SET generation = generation + 1
            """,
            (run_id,),
        )
        generation_row = _one(
            connection.execute(
                "SELECT generation FROM executor_generations WHERE run_id = ?",
                (run_id,),
            )
        )
        assert generation_row is not None  # noqa: S101
        generation = _integer(generation_row, "generation")
        token = f"{generation}:{uuid4().hex}"
        expires_at = started_at + ttl
        connection.execute(
            """
            INSERT INTO executor_leases(
                run_id, executor_id, token, generation,
                acquired_at, renewed_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                executor_id,
                token,
                generation,
                _timestamp(started_at),
                _timestamp(started_at),
                _timestamp(expires_at),
            ),
        )
        connection.executemany(
            """
            INSERT INTO resource_leases(
                resource_kind, resource_id, run_id, executor_token,
                status, acquired_at, expires_at
            )
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            [
                (
                    resource.kind,
                    resource.id,
                    run_id,
                    token,
                    _timestamp(started_at),
                    _timestamp(expires_at),
                )
                for resource in requirements
            ],
        )
        lease = ExecutorLease(
            run_id=run_id,
            executor_id=executor_id,
            token=token,
            generation=generation,
            acquired_at=started_at,
            renewed_at=started_at,
            expires_at=expires_at,
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind="executor_lease_granted",
                payload={
                    "executor_id": executor_id,
                    "generation": generation,
                    "expires_at": _timestamp(expires_at),
                },
                occurred_at=started_at,
            ),
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind="resources_claimed",
                payload={"count": len(requirements)},
                occurred_at=started_at,
            ),
        )
        self.transition_run_in_transaction(
            connection,
            run_id,
            expected_state="accepted",
            state="running",
            executor_token=token,
            at=started_at,
        )
        return lease

    def renew_executor_lease(
        self,
        token: str,
        *,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Renew an executor and its active resource claims together."""

        _ttl(ttl)
        renewed_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            lease = self._live_executor(connection, token, at=renewed_at)
            expires_at = renewed_at + ttl
            connection.execute(
                """
                UPDATE executor_leases SET renewed_at = ?, expires_at = ?
                WHERE token = ?
                """,
                (_timestamp(renewed_at), _timestamp(expires_at), token),
            )
            connection.execute(
                """
                UPDATE resource_leases SET expires_at = ?
                WHERE executor_token = ? AND status = 'active'
                """,
                (_timestamp(expires_at), token),
            )
            row = _one(
                connection.execute(
                    "SELECT * FROM executor_leases WHERE token = ?", (lease.token,)
                )
            )
            assert row is not None  # noqa: S101
            renewed = _executor(row)
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=lease.run_id,
                    kind="executor_lease_renewed",
                    payload={
                        "executor_id": lease.executor_id,
                        "generation": lease.generation,
                        "expires_at": _timestamp(expires_at),
                    },
                    occurred_at=renewed_at,
                ),
            )
            return renewed

    def validate_executor_lease(
        self,
        run_id: str,
        *,
        token: str,
        generation: int,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Resolve the exact live fencing generation carried by a wire command."""

        checked_at = at or datetime.now(tz=UTC)
        with closing(self._connect()) as connection:
            lease = self._live_executor(
                connection,
                token,
                at=checked_at,
                run_id=run_id,
            )
        if lease.generation != generation:
            raise ExecutorLeaseNotHeld("executor generation is stale")
        return lease

    @contextmanager
    def fenced_transaction(
        self,
        run_id: str,
        *,
        token: str,
        generation: int,
        at: datetime | None = None,
    ) -> Generator[sqlite3.Connection]:
        """Serialize lease validation with every durable executor effect."""

        with self._transaction() as connection:
            checked_at = at or datetime.now(tz=UTC)
            lease = self._live_executor(
                connection,
                token,
                at=checked_at,
                run_id=run_id,
            )
            if lease.generation != generation:
                raise ExecutorLeaseNotHeld("executor generation is stale")
            run = _run(self._require_run(connection, run_id))
            if run.state != "running":
                raise ControlPlaneConflict(
                    f"executor effects require a running run, got {run.state}"
                )
            yield connection

    def executor_lease_for_run(self, run_id: str) -> ExecutorLease | None:
        """Read the current executor lease for a run."""

        with closing(self._connect()) as connection:
            return self.executor_lease_for_run_in_transaction(connection, run_id)

    def executor_lease_for_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> ExecutorLease | None:
        """Read the current executor lease through an existing transaction."""

        row = _one(
            connection.execute(
                "SELECT * FROM executor_leases WHERE run_id = ?",
                (run_id,),
            )
        )
        return None if row is None else _executor(row)

    def release_executor_lease(self, token: str) -> bool:
        """Release an accepted run's executor and resources."""

        with self._transaction() as connection:
            row = _one(
                connection.execute(
                    "SELECT * FROM executor_leases WHERE token = ?", (token,)
                )
            )
            if row is None:
                return False
            lease = _executor(row)
            if _run(self._require_run(connection, lease.run_id)).state == "running":
                raise ControlPlaneConflict(
                    "a running executor must finish or require attention"
                )
            released = connection.execute(
                "DELETE FROM resource_leases WHERE executor_token = ?", (token,)
            ).rowcount
            connection.execute("DELETE FROM executor_leases WHERE token = ?", (token,))
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=lease.run_id,
                    kind="executor_lease_released",
                    payload={
                        "executor_id": lease.executor_id,
                        "generation": lease.generation,
                        "resource_count": released,
                    },
                ),
            )
            return True

    def claim_run_resources(
        self,
        token: str,
        *,
        at: datetime | None = None,
    ) -> ResourceClaimResult:
        """Claim every resource declared at admission, or none."""

        claimed_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            executor = self._live_executor(connection, token, at=claimed_at)
            requirements = self._requirements(connection, executor.run_id)
            existing: dict[tuple[str, str], ResourceLease] = {}
            conflicts: list[ResourceClaimConflict] = []
            for resource in requirements:
                row = _one(
                    connection.execute(
                        """
                        SELECT * FROM resource_leases
                        WHERE resource_kind = ? AND resource_id = ?
                        """,
                        (resource.kind, resource.id),
                    )
                )
                if row is None:
                    continue
                lease = _resource_lease(row)
                existing[(resource.kind, resource.id)] = lease
                if lease.executor_token != token:
                    conflicts.append(
                        ResourceClaimConflict(
                            resource=resource,
                            owner_run_id=lease.run_id,
                            status=lease.status,
                        )
                    )
            if conflicts:
                return ResourceClaimResult(
                    acquired=False,
                    conflicts=tuple(conflicts),
                )
            connection.executemany(
                """
                INSERT INTO resource_leases(
                    resource_kind, resource_id, run_id, executor_token,
                    status, acquired_at, expires_at
                )
                VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                [
                    (
                        resource.kind,
                        resource.id,
                        executor.run_id,
                        token,
                        _timestamp(claimed_at),
                        _timestamp(executor.expires_at),
                    )
                    for resource in requirements
                    if (resource.kind, resource.id) not in existing
                ],
            )
            leases = self._leases_for_token(connection, token)
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=executor.run_id,
                    kind="resources_claimed",
                    payload={"count": len(leases)},
                    occurred_at=claimed_at,
                ),
            )
            return ResourceClaimResult(
                acquired=True,
                leases=leases,
            )

    def list_resource_leases(self) -> tuple[ResourceLease, ...]:
        with closing(self._connect()) as connection:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM resource_leases
                    ORDER BY resource_kind, resource_id
                    """
                )
            )
        return tuple(_resource_lease(row) for row in rows)

    def release_run_resources(self, run_id: str) -> int:
        """Release reconciled quarantined resources."""

        with self._transaction() as connection:
            return self.release_run_resources_in_transaction(connection, run_id)

    def release_run_resources_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> int:
        """Release quarantined resources through an existing transaction."""

        run = _run(self._require_run(connection, run_id))
        if run.state not in {"attention_required", "terminal"}:
            raise ControlPlaneConflict(
                "only reconciled attention-required resources may be released"
            )
        cursor = connection.execute(
            "DELETE FROM resource_leases WHERE run_id = ?", (run_id,)
        )
        if cursor.rowcount:
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="resources_released",
                    payload={"count": cursor.rowcount},
                ),
            )
        return cursor.rowcount

    def expire_executor_leases(
        self,
        *,
        at: datetime | None = None,
    ) -> tuple[str, ...]:
        """Expire stale executors and quarantine resources of active runs."""

        expired_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            rows = _all(
                connection.execute(
                    """
                    SELECT run_id FROM executor_leases
                    WHERE expires_at <= ?
                    ORDER BY run_id
                    """,
                    (_timestamp(expired_at),),
                )
            )
            return tuple(
                run_id
                for row in rows
                if self._expire_one(
                    connection,
                    run_id := _text(row, "run_id"),
                    expired_at,
                )
            )

    def abandon_executor_leases(
        self,
        *,
        at: datetime | None = None,
    ) -> tuple[str, ...]:
        """Fence executors from the previous daemon process immediately."""

        abandoned_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            rows = _all(
                connection.execute("SELECT run_id FROM executor_leases ORDER BY run_id")
            )
            return tuple(
                run_id
                for row in rows
                if self._expire_one(
                    connection,
                    run_id := _text(row, "run_id"),
                    abandoned_at,
                    force=True,
                    attention_reason="daemon_restarted",
                )
            )

    def _transition_lease(
        self,
        connection: sqlite3.Connection,
        run: ControlRun,
        state: ControlRunState,
        token: str | None,
        at: datetime,
    ) -> ExecutorLease | None:
        lease: ExecutorLease | None = None
        if run.state == "running" or state == "running":
            if token is None:
                raise ExecutorLeaseNotHeld(
                    "running transitions require an executor token"
                )
            lease = self._live_executor(connection, token, at=at, run_id=run.run_id)
        elif token is not None:
            lease = self._live_executor(connection, token, at=at, run_id=run.run_id)
        if state == "running":
            required = {
                (resource.kind, resource.id)
                for resource in self._requirements(connection, run.run_id)
            }
            held = {
                (lease.resource.kind, lease.resource.id)
                for lease in self._leases_for_token(
                    connection,
                    cast("ExecutorLease", lease).token,
                )
            }
            if required != held:
                raise ControlPlaneConflict(
                    "executor must hold all admitted resources before running"
                )
        if run.state == "attention_required" and state == "accepted":
            claimed = _one(
                connection.execute(
                    "SELECT 1 AS claimed FROM resource_leases WHERE run_id = ?",
                    (run.run_id,),
                )
            )
            if claimed is not None:
                raise ControlPlaneConflict(
                    "release reconciled resources before requeueing"
                )
        return lease

    @staticmethod
    def _find_admission_conflict(
        connection: sqlite3.Connection,
        admission: RunAdmissionRecord,
    ) -> ControlRun | None:
        rows = _all(
            connection.execute(
                """
                SELECT * FROM runs
                WHERE run_id = ? OR submission_id = ?
                ORDER BY sequence
                """,
                (admission.run_id, admission.submission_id),
            )
        )
        if len(rows) != 1:
            return None
        existing = _run(rows[0])
        left = existing.admission.model_dump(exclude={"run_id", "admitted_at"})
        right = admission.model_dump(exclude={"run_id", "admitted_at"})
        return existing if left == right else None

    def _expire_one(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        at: datetime,
        *,
        force: bool = False,
        attention_reason: str = "executor_lease_expired",
    ) -> bool:
        row = _one(
            connection.execute(
                "SELECT * FROM executor_leases WHERE run_id = ?", (run_id,)
            )
        )
        if row is None:
            return False
        lease = _executor(row)
        if not force and lease.expires_at > at:
            return False
        run = _run(self._require_run(connection, run_id))
        active = run.state == "running"
        if active:
            quarantined = self._quarantine(connection, lease.token)
            connection.execute(
                """
                UPDATE runs SET
                    state = 'attention_required',
                    state_version = state_version + 1,
                    updated_at = ?,
                    attention_reason = ?
                WHERE run_id = ?
                """,
                (_timestamp(at), attention_reason, run_id),
            )
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="run_state_changed",
                    payload={
                        "from": "running",
                        "to": "attention_required",
                        "state_version": run.state_version + 1,
                    },
                    occurred_at=at,
                ),
            )
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="resources_quarantined",
                    payload={"count": quarantined},
                    occurred_at=at,
                ),
            )
        else:
            released = connection.execute(
                "DELETE FROM resource_leases WHERE executor_token = ?",
                (lease.token,),
            ).rowcount
            if released:
                self._insert_event(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="resources_released",
                        payload={"count": released},
                        occurred_at=at,
                    ),
                )
        connection.execute(
            "DELETE FROM executor_leases WHERE token = ?", (lease.token,)
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind="executor_lease_lost",
                payload={
                    "executor_id": lease.executor_id,
                    "generation": lease.generation,
                    "reason": attention_reason,
                },
                occurred_at=at,
            ),
        )
        return active

    @staticmethod
    def _quarantine(connection: sqlite3.Connection, token: str) -> int:
        return connection.execute(
            """
            UPDATE resource_leases SET
                executor_token = NULL, status = 'quarantined', expires_at = NULL
            WHERE executor_token = ?
            """,
            (token,),
        ).rowcount

    @staticmethod
    def _requirements(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> tuple[ResourceKey, ...]:
        rows = _all(
            connection.execute(
                """
                SELECT resource_kind, resource_id
                FROM run_resource_requirements
                WHERE run_id = ?
                ORDER BY resource_kind, resource_id
                """,
                (run_id,),
            )
        )
        return tuple(
            ResourceKey.model_validate(
                {
                    "kind": _text(row, "resource_kind"),
                    "id": _text(row, "resource_id"),
                }
            )
            for row in rows
        )

    @staticmethod
    def _leases_for_token(
        connection: sqlite3.Connection,
        token: str,
    ) -> tuple[ResourceLease, ...]:
        rows = _all(
            connection.execute(
                """
                SELECT * FROM resource_leases
                WHERE executor_token = ?
                ORDER BY resource_kind, resource_id
                """,
                (token,),
            )
        )
        return tuple(_resource_lease(row) for row in rows)

    @staticmethod
    def _live_executor(
        connection: sqlite3.Connection,
        token: str,
        *,
        at: datetime,
        run_id: str | None = None,
    ) -> ExecutorLease:
        row = _one(
            connection.execute(
                "SELECT * FROM executor_leases WHERE token = ?", (token,)
            )
        )
        if row is None:
            raise ExecutorLeaseNotHeld("executor token is not held")
        lease = _executor(row)
        if run_id is not None and lease.run_id != run_id:
            raise ExecutorLeaseNotHeld("executor token belongs to another run")
        if lease.expires_at <= at:
            raise ExecutorLeaseNotHeld("executor token has expired")
        return lease

    @staticmethod
    def _require_run(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> sqlite3.Row:
        row = _one(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)))
        if row is None:
            raise ControlPlaneNotFound(f"run was not found: {run_id}")
        return row

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        event: DurableEventInput,
    ) -> DurableEvent:
        cursor = connection.execute(
            """
            INSERT INTO durable_events(run_id, kind, payload_json, occurred_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.kind,
                _json(event.payload),
                _timestamp(event.occurred_at),
            ),
        )
        return DurableEvent(
            event_id=cast("int", cursor.lastrowid),
            run_id=event.run_id,
            kind=event.kind,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Open one daemon-owned write unit spanning SQLite adapters."""

        with self._transaction() as connection:
            yield connection

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=self._busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection


def _run(row: sqlite3.Row) -> ControlRun:
    outcome_json = _optional_text(row, "outcome_json")
    return ControlRun(
        sequence=_integer(row, "sequence"),
        admission=RunAdmissionRecord.model_validate_json(_text(row, "admission_json")),
        state=cast("ControlRunState", _text(row, "state")),
        state_version=_integer(row, "state_version"),
        updated_at=_datetime(_text(row, "updated_at")),
        outcome=(
            RunOutcome.model_validate_json(outcome_json)
            if outcome_json is not None
            else None
        ),
        attention_reason=_optional_text(row, "attention_reason"),
    )


def _event(row: sqlite3.Row) -> DurableEvent:
    return DurableEvent(
        event_id=_integer(row, "event_id"),
        run_id=_optional_text(row, "run_id"),
        kind=_text(row, "kind"),
        payload=_JSON_OBJECT.validate_json(_text(row, "payload_json")),
        occurred_at=_datetime(_text(row, "occurred_at")),
    )


def _executor(row: sqlite3.Row) -> ExecutorLease:
    return ExecutorLease(
        run_id=_text(row, "run_id"),
        executor_id=_text(row, "executor_id"),
        token=_text(row, "token"),
        generation=_integer(row, "generation"),
        acquired_at=_datetime(_text(row, "acquired_at")),
        renewed_at=_datetime(_text(row, "renewed_at")),
        expires_at=_datetime(_text(row, "expires_at")),
    )


def _resource_lease(row: sqlite3.Row) -> ResourceLease:
    expires_at = _optional_text(row, "expires_at")
    return ResourceLease.model_validate(
        {
            "resource": {
                "kind": _text(row, "resource_kind"),
                "id": _text(row, "resource_id"),
            },
            "run_id": _text(row, "run_id"),
            "executor_token": _optional_text(row, "executor_token"),
            "status": _text(row, "status"),
            "acquired_at": _datetime(_text(row, "acquired_at")),
            "expires_at": _datetime(expires_at) if expires_at is not None else None,
        }
    )


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, name: str) -> str:
    return cast("str", row[name])


def _optional_text(row: sqlite3.Row, name: str) -> str | None:
    return cast("str | None", row[name])


def _integer(row: sqlite3.Row, name: str) -> int:
    return cast("int", row[name])


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "control-plane timestamps must be timezone-aware"
        raise ValueError(msg)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json(value: dict[str, JsonValue]) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _page_size(limit: int) -> None:
    if not 1 <= limit <= 500:
        msg = "page size must be between 1 and 500"
        raise ValueError(msg)


def _ttl(ttl: timedelta) -> None:
    if ttl <= timedelta(0):
        msg = "lease ttl must be positive"
        raise ValueError(msg)
