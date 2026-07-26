"""SQLite control plane for a daemon-owned project."""

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

from scopecat.adapters.sqlite.connection import connect, immediate_transaction
from scopecat.control.models import (
    ControlRun,
    ControlRunState,
    DurableEvent,
    DurableEventInput,
    EventPage,
    ExecutorLease,
    ResourceKey,
    ResourceLease,
    RunAdmissionRecord,
    RunPage,
)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ControlPlaneError(RuntimeError):
    """Base failure from the SQLite control plane."""


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
        self._busy_timeout_seconds = (
            busy_timeout or timedelta(seconds=5)
        ).total_seconds()

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
                INSERT INTO scheduler_runs(
                    submission_id, run_id, state, updated_at,
                    admission_json, attention_reason
                )
                VALUES (?, ?, 'queued', ?, ?, NULL)
                """,
                (
                    admission.submission_id,
                    admission.run_id,
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
                    "experiment_id": admission.experiment_id,
                    "submission_id": admission.submission_id,
                },
                occurred_at=admission.admitted_at,
            ),
        )
        row = _one(
            connection.execute(
                "SELECT * FROM scheduler_runs WHERE sequence = ?",
                (cast("int", cursor.lastrowid),),
            )
        )
        assert row is not None
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

    def list_runs(
        self,
        *,
        limit: int = 50,
        after: int | None = None,
        before: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunPage:
        """Return a keyset page in immutable admission order."""

        with closing(self._connect()) as connection:
            return self.list_runs_in_transaction(
                connection,
                limit=limit,
                after=after,
                before=before,
                state=state,
                latest=latest,
            )

    def list_runs_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        limit: int = 50,
        after: int | None = None,
        before: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunPage:
        """Read one scheduler page through an existing SQLite snapshot."""

        _page_size(limit)
        if after is not None and before is not None:
            raise ValueError("run pages accept either an after or before cursor")
        if latest and (after is not None or before is not None):
            raise ValueError("latest run snapshots do not accept a cursor")
        cursor = after or 0
        if latest and state is None:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM scheduler_runs
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (limit + 1,),
                )
            )
        elif latest:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM scheduler_runs
                    WHERE state = ?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (state, limit + 1),
                )
            )
        elif before is not None and state is None:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM scheduler_runs
                    WHERE sequence < ?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (before, limit + 1),
                )
            )
        elif before is not None:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM scheduler_runs
                    WHERE sequence < ? AND state = ?
                    ORDER BY sequence DESC
                    LIMIT ?
                    """,
                    (before, state, limit + 1),
                )
            )
        elif state is None:
            rows = _all(
                connection.execute(
                    """
                    SELECT * FROM scheduler_runs
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
                    SELECT * FROM scheduler_runs
                    WHERE sequence > ? AND state = ?
                    ORDER BY sequence
                    LIMIT ?
                    """,
                    (cursor, state, limit + 1),
                )
            )
        if latest or before is not None:
            page_rows = rows[:limit]
            page_rows.reverse()
            items = tuple(_run(row) for row in page_rows)
            previous_cursor = items[0].sequence if len(rows) > limit and items else None
            return RunPage(items=items, previous_cursor=previous_cursor)
        items = tuple(_run(row) for row in rows[:limit])
        next_cursor = None if len(rows) <= limit else items[-1].sequence
        return RunPage(items=items, next_cursor=next_cursor)

    def close_run_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        executor_token: str | None = None,
        at: datetime | None = None,
    ) -> ControlRun:
        """Close scheduling after the terminal outcome is committed."""

        current = _run(self._require_run(connection, run_id))
        closed_at = at or datetime.now(tz=UTC)
        if current.state == "leased":
            if executor_token is None:
                raise ExecutorLeaseNotHeld(
                    "closing a leased run requires its executor token"
                )
            self._live_executor(
                connection,
                executor_token,
                at=closed_at,
                run_id=run_id,
            )
        elif current.state == "attention_required":
            if executor_token is not None:
                raise ControlPlaneConflict(
                    "attention-required runs no longer have an executor"
                )
        else:
            raise ControlPlaneConflict(
                f"only leased or attention-required runs can close, got {current.state}"
            )

        updated = self._update_scheduler_state_in_transaction(
            connection,
            current,
            state="closed",
            at=closed_at,
        )
        released = connection.execute(
            "DELETE FROM resource_leases WHERE run_id = ?", (run_id,)
        ).rowcount
        connection.execute("DELETE FROM executor_leases WHERE run_id = ?", (run_id,))
        if released:
            self._insert_event(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="resources_released",
                    payload={"count": released},
                    occurred_at=closed_at,
                ),
            )
        return updated

    def _update_scheduler_state_in_transaction(
        self,
        connection: sqlite3.Connection,
        current: ControlRun,
        *,
        state: ControlRunState,
        at: datetime,
        attention_reason: str | None = None,
    ) -> ControlRun:
        updated = ControlRun.model_validate(
            {
                **current.model_dump(),
                "state": state,
                "updated_at": at,
                "attention_reason": attention_reason,
            }
        )
        connection.execute(
            """
            UPDATE scheduler_runs SET
                state = ?, updated_at = ?, attention_reason = ?
            WHERE run_id = ?
            """,
            (state, _timestamp(at), attention_reason, current.run_id),
        )
        self._insert_event(
            connection,
            DurableEventInput(
                run_id=current.run_id,
                kind="run_state_changed",
                payload={"from": current.state, "to": state},
                occurred_at=at,
            ),
        )
        return updated

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

    def start_execution_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        executor_id: str,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Lease every declared resource and enter the leased scheduler state."""

        _ttl(ttl)
        started_at = at or datetime.now(tz=UTC)
        self._expire_one(connection, run_id, started_at)
        run = _run(self._require_run(connection, run_id))
        if run.state != "queued":
            raise ControlPlaneConflict(
                f"executor can only start a queued run, got {run.state}"
            )
        requirements = self._requirements(connection, run_id)
        conflicts: list[ResourceKey] = []
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
            conflicts.append(resource)
        if conflicts:
            owners = ", ".join(
                f"{resource.kind}:{resource.id}" for resource in conflicts
            )
            raise ControlPlaneConflict(f"run resources are busy: {owners}")

        token = uuid4().hex
        expires_at = started_at + ttl
        connection.execute(
            """
            INSERT INTO executor_leases(
                run_id, executor_id, token, acquired_at, renewed_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                executor_id,
                token,
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
        self._update_scheduler_state_in_transaction(
            connection,
            run,
            state="leased",
            at=started_at,
        )
        return lease

    def renew_executor_lease(
        self,
        run_id: str,
        token: str,
        *,
        ttl: timedelta,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Renew an executor and its active resource claims together."""

        _ttl(ttl)
        renewed_at = at or datetime.now(tz=UTC)
        with self._transaction() as connection:
            lease = self._live_executor(
                connection,
                token,
                at=renewed_at,
                run_id=run_id,
            )
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
            assert row is not None
            return _executor(row)

    def validate_executor_lease(
        self,
        run_id: str,
        *,
        token: str,
        at: datetime | None = None,
    ) -> ExecutorLease:
        """Resolve the exact live fencing token carried by a wire command."""

        checked_at = at or datetime.now(tz=UTC)
        with closing(self._connect()) as connection:
            lease = self._live_executor(
                connection,
                token,
                at=checked_at,
                run_id=run_id,
            )
        return lease

    @contextmanager
    def fenced_transaction(
        self,
        run_id: str,
        *,
        token: str,
        at: datetime | None = None,
    ) -> Generator[sqlite3.Connection]:
        """Serialize lease validation with every durable executor effect."""

        with self._transaction() as connection:
            checked_at = at or datetime.now(tz=UTC)
            self._live_executor(
                connection,
                token,
                at=checked_at,
                run_id=run_id,
            )
            run = _run(self._require_run(connection, run_id))
            if run.state != "leased":
                raise ControlPlaneConflict(
                    f"executor effects require a leased run, got {run.state}"
                )
            yield connection

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

    def list_resource_leases_in_transaction(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[ResourceLease, ...]:
        """Read resource leases through an existing SQLite snapshot."""

        rows = _all(
            connection.execute(
                """
                SELECT * FROM resource_leases
                ORDER BY resource_kind, resource_id
                """
            )
        )
        return tuple(_resource_lease(row) for row in rows)

    def release_run_resources_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> int:
        """Release quarantined resources through an existing transaction."""

        run = _run(self._require_run(connection, run_id))
        if run.state not in {"attention_required", "closed"}:
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

    @staticmethod
    def _find_admission_conflict(
        connection: sqlite3.Connection,
        admission: RunAdmissionRecord,
    ) -> ControlRun | None:
        rows = _all(
            connection.execute(
                """
                SELECT * FROM scheduler_runs
                WHERE run_id = ? OR submission_id = ?
                ORDER BY sequence
                """,
                (admission.run_id, admission.submission_id),
            )
        )
        if len(rows) != 1:
            return None
        existing = _run(rows[0])
        return existing if admission.is_retry_of(existing.admission) else None

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
        active = run.state == "leased"
        if active:
            quarantined = self._quarantine(connection, lease.token)
            self._update_scheduler_state_in_transaction(
                connection,
                run,
                state="attention_required",
                at=at,
                attention_reason=attention_reason,
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
        row = _one(
            connection.execute(
                "SELECT * FROM scheduler_runs WHERE run_id = ?",
                (run_id,),
            )
        )
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
        with immediate_transaction(
            self.path,
            busy_timeout_seconds=self._busy_timeout_seconds,
        ) as connection:
            yield connection

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection]:
        """Open one daemon-owned write unit spanning SQLite adapters."""

        with self._transaction() as connection:
            yield connection

    def _connect(self) -> sqlite3.Connection:
        return connect(
            self.path,
            busy_timeout_seconds=self._busy_timeout_seconds,
        )


def _run(row: sqlite3.Row) -> ControlRun:
    return ControlRun(
        sequence=_integer(row, "sequence"),
        admission=RunAdmissionRecord.model_validate_json(_text(row, "admission_json")),
        state=cast("ControlRunState", _text(row, "state")),
        updated_at=_datetime(_text(row, "updated_at")),
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
