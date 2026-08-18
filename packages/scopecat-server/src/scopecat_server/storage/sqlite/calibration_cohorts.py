"""SQLite persistence and consistent status reads for calibration cohorts."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import ValidationError
from scopecat.automation.calibrations import (
    CalibrationAttemptStatus,
    CalibrationCohort,
    CalibrationCohortMember,
    CalibrationCohortSummary,
    CalibrationStatus,
    CalibrationStatusSnapshot,
    CalibrationSuccessPublication,
    CalibrationSuccessRef,
)
from scopecat.automation.models import ProcedureRun
from scopecat.daemon.wire import ConfigPublishReceipt

from scopecat_server.storage.sqlite.connection import SQLiteDatabase

_ACTIVE_CALIBRATION_COUNT_SQL = """
SELECT COUNT(*) AS active_count
FROM calibration_cohort_members AS members
JOIN calibration_cohorts AS cohorts
  ON cohorts.cohort_id = members.cohort_id
JOIN procedure_runs AS runs
  ON runs.procedure_run_id = members.procedure_run_id
WHERE cohorts.fanout_scope = ?
  AND runs.state IN ('ready', 'leased', 'waiting', 'attention_required')
"""


class CalibrationCohortStoreError(RuntimeError):
    """Durable calibration cohort state could not be read or committed."""


class CalibrationCohortNotFound(CalibrationCohortStoreError):
    """A requested durable calibration cohort does not exist."""


class CalibrationCohortConflict(CalibrationCohortStoreError):
    """A calibration cohort command conflicts with durable state."""


@dataclass(frozen=True, slots=True)
class StoredCalibrationCohortPage:
    """Newest-first keyset page of calibration cohort summaries."""

    items: tuple[CalibrationCohortSummary, ...]
    next_cursor: int | None = None


@dataclass(frozen=True, slots=True)
class StoredCalibrationCohortMemberPage:
    """Admission-order keyset page of one cohort's members."""

    items: tuple[CalibrationCohortMember, ...]
    next_cursor: int | None = None


class SQLiteCalibrationCohortStore:
    """Immutable cohorts joined to live durable ProcedureRun state."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.sqlite = database
        self.database = database.path

    @contextmanager
    def read_transaction(self) -> Generator[sqlite3.Connection]:
        with self.sqlite.read_transaction() as connection:
            yield connection

    @contextmanager
    def write_transaction(self) -> Generator[sqlite3.Connection]:
        with self.sqlite.write_transaction() as connection:
            yield connection

    def read(self, cohort_id: str) -> CalibrationCohort:
        with self.sqlite.read_connection() as connection:
            return self.read_in_transaction(connection, cohort_id)

    def read_in_transaction(
        self,
        connection: sqlite3.Connection,
        cohort_id: str,
    ) -> CalibrationCohort:
        try:
            row = _one(
                connection.execute(
                    """
                    SELECT cohort_json
                    FROM calibration_cohorts
                    WHERE cohort_id = ?
                    """,
                    (cohort_id,),
                )
            )
        except sqlite3.Error as error:
            raise CalibrationCohortStoreError(
                f"failed to read calibration cohort: {cohort_id}"
            ) from error
        if row is None:
            raise CalibrationCohortNotFound(
                f"calibration cohort was not found: {cohort_id}"
            )
        return _cohort(row)

    def list(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        fanout_scope: str | None = None,
    ) -> StoredCalibrationCohortPage:
        if not 1 <= limit <= 200:
            raise ValueError("calibration cohort page size must be between 1 and 200")
        if before is not None and before < 1:
            raise ValueError("calibration cohort cursor must be positive")
        clauses: list[str] = []
        parameters: list[str | int] = []
        if before is not None:
            clauses.append("sequence < ?")
            parameters.append(before)
        if fanout_scope is not None:
            clauses.append("fanout_scope = ?")
            parameters.append(fanout_scope)
        where = "" if not clauses else f"WHERE {' AND '.join(clauses)}"
        parameters.append(limit + 1)
        try:
            with self.sqlite.read_connection() as connection:
                rows = _all(
                    connection.execute(
                        f"""
                        SELECT sequence, cohort_json
                        FROM calibration_cohorts
                        {where}
                        ORDER BY sequence DESC
                        LIMIT ?
                        """,  # noqa: S608 - clauses are fixed internal fragments
                        parameters,
                    )
                )
            selected = rows[:limit]
            return StoredCalibrationCohortPage(
                items=tuple(
                    CalibrationCohortSummary.from_cohort(_cohort(row))
                    for row in selected
                ),
                next_cursor=(
                    _integer(selected[-1], "sequence") if len(rows) > limit else None
                ),
            )
        except (sqlite3.Error, ValidationError) as error:
            raise CalibrationCohortStoreError(
                "failed to list calibration cohorts"
            ) from error

    def list_members(
        self,
        cohort_id: str,
        *,
        limit: int = 50,
        after: int | None = None,
    ) -> StoredCalibrationCohortMemberPage:
        if not 1 <= limit <= 200:
            raise ValueError(
                "calibration cohort member page size must be between 1 and 200"
            )
        if after is not None and after < 0:
            raise ValueError("calibration cohort member cursor cannot be negative")
        try:
            with self.sqlite.read_transaction() as connection:
                self.read_in_transaction(connection, cohort_id)
                rows = _all(
                    connection.execute(
                        """
                        SELECT member_index, member_json
                        FROM calibration_cohort_members
                        WHERE cohort_id = ?
                          AND (? IS NULL OR member_index > ?)
                        ORDER BY member_index ASC
                        LIMIT ?
                        """,
                        (cohort_id, after, after, limit + 1),
                    )
                )
            selected = rows[:limit]
            return StoredCalibrationCohortMemberPage(
                items=tuple(_member(row) for row in selected),
                next_cursor=(
                    _integer(selected[-1], "member_index")
                    if len(rows) > limit
                    else None
                ),
            )
        except (sqlite3.Error, ValidationError) as error:
            raise CalibrationCohortStoreError(
                f"failed to list calibration cohort members: {cohort_id}"
            ) from error

    def list_members_in_transaction(
        self,
        connection: sqlite3.Connection,
        cohort_id: str,
    ) -> tuple[CalibrationCohortMember, ...]:
        try:
            rows = _all(
                connection.execute(
                    """
                    SELECT member_json
                    FROM calibration_cohort_members
                    WHERE cohort_id = ?
                    ORDER BY member_index ASC
                    """,
                    (cohort_id,),
                )
            )
            return tuple(_member(row) for row in rows)
        except (sqlite3.Error, ValidationError) as error:
            raise CalibrationCohortStoreError(
                f"failed to read calibration cohort members: {cohort_id}"
            ) from error

    def status_snapshot(
        self,
        calibration_keys: tuple[str, ...],
        *,
        fanout_scope: str,
        clock: Callable[[], datetime],
    ) -> CalibrationStatusSnapshot:
        with self.sqlite.read_transaction() as connection:
            return self.status_snapshot_in_transaction(
                connection,
                calibration_keys,
                fanout_scope=fanout_scope,
                clock=clock,
            )

    def status_snapshot_in_transaction(
        self,
        connection: sqlite3.Connection,
        calibration_keys: tuple[str, ...],
        *,
        fanout_scope: str,
        clock: Callable[[], datetime],
    ) -> CalibrationStatusSnapshot:
        try:
            rows = self._status_rows_in_transaction(connection, calibration_keys)
            statuses = _statuses(calibration_keys, rows)
            active_row = _one(
                connection.execute(
                    _ACTIVE_CALIBRATION_COUNT_SQL,
                    (fanout_scope,),
                )
            )
            assert active_row is not None
            return CalibrationStatusSnapshot(
                # SQLite fixes a deferred read transaction at its first SELECT.
                # Sample the server clock only after every projection has been
                # read from that snapshot, so no included transition can follow
                # the advertised observation time.
                observed_at=clock(),
                fanout_scope=fanout_scope,
                fanout_active_count=_integer(active_row, "active_count"),
                statuses=statuses,
            )
        except (sqlite3.Error, ValidationError) as error:
            raise CalibrationCohortStoreError(
                "failed to read calibration status snapshot"
            ) from error

    def _status_rows_in_transaction(
        self,
        connection: sqlite3.Connection,
        calibration_keys: tuple[str, ...],
    ) -> list[sqlite3.Row]:
        if not calibration_keys:
            return []
        query, parameters = _status_rows_query(calibration_keys)
        return _all(
            connection.execute(
                query,
                parameters,
            )
        )

    def insert_cohort_in_transaction(
        self,
        connection: sqlite3.Connection,
        cohort: CalibrationCohort,
    ) -> None:
        generation = cohort.spec.config_source.registry_generation
        try:
            connection.execute(
                """
                INSERT INTO calibration_cohorts(
                    cohort_id, planner_id, planner_version, planner_fingerprint,
                    spec_hash, fanout_scope, member_count, config_generation,
                    evaluated_at, created_at, cohort_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cohort.cohort_id,
                    cohort.spec.planner.id,
                    cohort.spec.planner.version,
                    cohort.spec.planner.fingerprint,
                    cohort.spec_hash,
                    cohort.spec.fanout_scope,
                    len(cohort.spec.members),
                    generation,
                    _timestamp(cohort.spec.evaluated_at),
                    _timestamp(cohort.created_at),
                    cohort.model_dump_json(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise CalibrationCohortConflict(
                "calibration cohort id already has durable state"
            ) from error
        except sqlite3.Error as error:
            raise CalibrationCohortStoreError(
                "failed to insert calibration cohort"
            ) from error

    def insert_member_in_transaction(
        self,
        connection: sqlite3.Connection,
        member: CalibrationCohortMember,
    ) -> None:
        try:
            inserted = connection.execute(
                """
                INSERT INTO calibration_cohort_members(
                    cohort_id, member_index, member_id, calibration_key,
                    procedure_run_id, request_key, admitted_at,
                    closure_status, closed_at, member_json
                )
                SELECT ?, ?, ?, ?, ?, ?, ?,
                       runs.closure_status, runs.closed_at, ?
                FROM procedure_runs AS runs
                WHERE runs.procedure_run_id = ?
                """,
                (
                    member.cohort_id,
                    member.index,
                    member.spec.member_id,
                    member.spec.calibration_key,
                    member.procedure_run_id,
                    member.request_key,
                    _timestamp(member.admitted_at),
                    member.model_dump_json(),
                    member.procedure_run_id,
                ),
            ).rowcount
            if inserted != 1:
                raise CalibrationCohortConflict(
                    "calibration cohort member procedure run was not found"
                )
        except sqlite3.IntegrityError as error:
            raise CalibrationCohortConflict(
                "calibration cohort member conflicts with durable state"
            ) from error
        except sqlite3.Error as error:
            raise CalibrationCohortStoreError(
                "failed to insert calibration cohort member"
            ) from error

    def insert_success_publication_in_transaction(
        self,
        connection: sqlite3.Connection,
        success: CalibrationSuccessRef,
    ) -> None:
        """Attach one config publication to its exact successful cohort member."""

        publication = success.publication
        if publication is None:
            raise ValueError("calibration success publication is required")
        try:
            row = _one(
                connection.execute(
                    """
                    SELECT members.member_json, members.closure_status,
                           members.closed_at, cohorts.cohort_json, runs.run_json
                    FROM calibration_cohort_members AS members
                    CROSS JOIN calibration_cohorts AS cohorts
                      ON cohorts.cohort_id = members.cohort_id
                    CROSS JOIN procedure_runs AS runs
                      ON runs.procedure_run_id = members.procedure_run_id
                    WHERE members.procedure_run_id = ?
                    """,
                    (success.attempt.procedure_run_id,),
                )
            )
            if row is None:
                raise CalibrationCohortConflict(
                    "calibration publication member was not found"
                )
            member = _member(row)
            cohort = _cohort(row)
            run = _run(row)
            if (
                member.cohort_id != cohort.cohort_id
                or success.attempt != member.attempt_ref
                or success.base_config_source != cohort.spec.config_source
                or run.state != "closed"
                or run.closure is None
                or run.closure.status != "succeeded"
                or success.succeeded_at != run.closure.closed_at
            ):
                raise CalibrationCohortConflict(
                    "calibration publication does not match its exact member success"
                )
            operation_row = _one(
                connection.execute(
                    """
                    SELECT receipt_json
                    FROM config_operations
                    WHERE operation_id = ? AND kind = 'publish_revision'
                    """,
                    (publication.operation_id,),
                )
            )
            if operation_row is None:
                raise CalibrationCohortConflict(
                    "calibration publication config operation was not found"
                )
            receipt = ConfigPublishReceipt.model_validate_json(
                _text(operation_row, "receipt_json")
            )
            result_source = publication.result_config_source
            base_source = success.base_config_source
            if (
                receipt.operation.operation_id != publication.operation_id
                or receipt.operation.source_intent_hash
                != publication.source_intent_hash
                or receipt.operation.expected_generation
                != base_source.registry_generation
                or receipt.activation.previous_entry_id != base_source.entry_id
                or receipt.activation.previous_entry_content_hash
                != base_source.content_hash
                or receipt.entry.id != result_source.entry_id
                or receipt.entry.config_ref != result_source.config_ref
                or receipt.entry.content_hash != result_source.content_hash
                or receipt.activation.generation != result_source.registry_generation
                or receipt.activation.recorded_at != publication.published_at
            ):
                raise CalibrationCohortConflict(
                    "calibration publication does not match its config operation"
                )
            connection.execute(
                """
                INSERT INTO calibration_success_publications(
                    procedure_run_id, cohort_id, member_id, calibration_key,
                    operation_id, source_intent_hash, result_input_fingerprint,
                    result_freshness_fingerprint, result_entry_id,
                    result_config_ref, result_content_hash,
                    result_registry_generation, published_at, publication_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    success.attempt.procedure_run_id,
                    success.attempt.cohort_id,
                    success.attempt.member_id,
                    success.attempt.calibration_key,
                    publication.operation_id,
                    publication.source_intent_hash,
                    publication.result_input_fingerprint,
                    publication.result_freshness_fingerprint,
                    result_source.entry_id,
                    result_source.config_ref,
                    result_source.content_hash,
                    result_source.registry_generation,
                    _timestamp(publication.published_at),
                    publication.model_dump_json(),
                ),
            )
        except CalibrationCohortConflict:
            raise
        except sqlite3.IntegrityError as error:
            raise CalibrationCohortConflict(
                "calibration success already has a different publication"
            ) from error
        except (sqlite3.Error, ValidationError) as error:
            raise CalibrationCohortStoreError(
                "failed to insert calibration success publication"
            ) from error


def _status_rows_query(
    calibration_keys: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    if not calibration_keys:
        raise ValueError("calibration status row query requires at least one key")
    requested = ", ".join("(?)" for _key in calibration_keys)
    query = f"""
    WITH requested(calibration_key) AS MATERIALIZED (
        VALUES {requested}
    ),
    chosen AS MATERIALIZED (
        SELECT requested.calibration_key,
               (
                   SELECT latest_attempt.sequence
                   FROM calibration_cohort_members AS latest_attempt
                   WHERE latest_attempt.calibration_key = requested.calibration_key
                   ORDER BY latest_attempt.sequence DESC
                   LIMIT 1
               ) AS latest_attempt_sequence,
               (
                   SELECT latest_success.sequence
                   FROM calibration_cohort_members AS latest_success
                   WHERE latest_success.calibration_key = requested.calibration_key
                     AND latest_success.closure_status = 'succeeded'
                   ORDER BY latest_success.sequence DESC
                   LIMIT 1
               ) AS latest_success_sequence
        FROM requested
    ),
    selected(sequence) AS (
        SELECT latest_attempt_sequence
        FROM chosen
        WHERE latest_attempt_sequence IS NOT NULL
        UNION
        SELECT latest_success_sequence
        FROM chosen
        WHERE latest_success_sequence IS NOT NULL
    )
    SELECT members.calibration_key, members.member_json, cohorts.cohort_json,
           members.sequence AS member_sequence,
           runs.run_json, members.closure_status, members.closed_at,
           publications.publication_json
    FROM selected
    CROSS JOIN calibration_cohort_members AS members
      ON members.sequence = selected.sequence
    CROSS JOIN procedure_runs AS runs
      ON runs.procedure_run_id = members.procedure_run_id
    CROSS JOIN calibration_cohorts AS cohorts
      ON cohorts.cohort_id = members.cohort_id
    LEFT JOIN calibration_success_publications AS publications
      ON publications.procedure_run_id = members.procedure_run_id
    ORDER BY members.sequence DESC
    """  # noqa: S608 - requested contains only generated placeholders
    return query, calibration_keys


def _statuses(
    calibration_keys: tuple[str, ...],
    rows: list[sqlite3.Row],
) -> tuple[CalibrationStatus, ...]:
    latest_attempts: dict[str, CalibrationAttemptStatus] = {}
    latest_successes: dict[str, CalibrationSuccessRef] = {}
    for row in rows:
        key = _text(row, "calibration_key")
        member = _member(row)
        cohort = _cohort(row)
        if member.cohort_id != cohort.cohort_id:
            raise CalibrationCohortStoreError(
                "calibration status member does not match its cohort"
            )
        run = _run(row)
        attempt = CalibrationAttemptStatus(
            attempt=member.attempt_ref,
            procedure_state=run.state,
            procedure_revision=run.revision,
            updated_at=run.updated_at,
            closure=run.closure,
        )
        latest_attempts.setdefault(key, attempt)
        if _optional_text(row, "closure_status") == "succeeded":
            closed_at = _optional_text(row, "closed_at")
            if closed_at is None:
                raise CalibrationCohortStoreError(
                    "successful calibration attempt is missing closed_at"
                )
            latest_successes.setdefault(
                key,
                CalibrationSuccessRef(
                    attempt=member.attempt_ref,
                    base_config_source=cohort.spec.config_source,
                    succeeded_at=datetime.fromisoformat(closed_at),
                    publication=_publication(row),
                ),
            )
    return tuple(
        CalibrationStatus(
            calibration_key=key,
            latest_attempt=latest_attempts.get(key),
            latest_success=latest_successes.get(key),
        )
        for key in calibration_keys
    )


def _cohort(row: sqlite3.Row) -> CalibrationCohort:
    try:
        return CalibrationCohort.model_validate_json(_text(row, "cohort_json"))
    except ValidationError as error:
        raise CalibrationCohortStoreError(
            "invalid durable calibration cohort"
        ) from error


def _member(row: sqlite3.Row) -> CalibrationCohortMember:
    try:
        return CalibrationCohortMember.model_validate_json(_text(row, "member_json"))
    except ValidationError as error:
        raise CalibrationCohortStoreError(
            "invalid durable calibration cohort member"
        ) from error


def _run(row: sqlite3.Row) -> ProcedureRun:
    try:
        return ProcedureRun.model_validate_json(_text(row, "run_json"))
    except ValidationError as error:
        raise CalibrationCohortStoreError(
            "invalid durable calibration procedure run"
        ) from error


def _publication(row: sqlite3.Row) -> CalibrationSuccessPublication | None:
    publication_json = _optional_text(row, "publication_json")
    if publication_json is None:
        return None
    try:
        return CalibrationSuccessPublication.model_validate_json(publication_json)
    except ValidationError as error:
        raise CalibrationCohortStoreError(
            "invalid durable calibration success publication"
        ) from error


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("calibration cohort timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, key: str) -> str:
    return cast("str", row[key])


def _optional_text(row: sqlite3.Row, key: str) -> str | None:
    return cast("str | None", row[key])


def _integer(row: sqlite3.Row, key: str) -> int:
    return cast("int", row[key])


__all__ = [
    "CalibrationCohortConflict",
    "CalibrationCohortNotFound",
    "CalibrationCohortStoreError",
    "SQLiteCalibrationCohortStore",
    "StoredCalibrationCohortMemberPage",
    "StoredCalibrationCohortPage",
]
