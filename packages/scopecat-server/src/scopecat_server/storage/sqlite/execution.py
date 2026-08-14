"""SQLite execution persistence backed by the shared project store."""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from pydantic_core import PydanticSerializationError
from scopecat.adaptive_domains import ResolvedDomainFragment
from scopecat.daemon.points import (
    AcceptedRunPointView,
    RunDomainDecisionCommand,
    RunDomainDecisionView,
    RunDomainEnqueueCommand,
    RunDomainQueueEntryView,
    RunDomainQueueView,
    RunPointPlanCloseCommand,
    RunPointPlanView,
)
from scopecat.records.measurement import MeasurementDatasetSchema, MeasurementRecord
from scopecat.records.measurement_recording import (
    CANONICAL_MEASUREMENT_DATASET_REF,
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.sdk.journal import ExecutionJournalError

from scopecat_server.storage.sqlite.object_store import ObjectStoreError, StoredObject
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository


class ExecutionJournalConflict(ExecutionJournalError):
    """A write disagrees with already committed execution state."""


@dataclass(frozen=True, slots=True)
class PreparedExecutionRecord[TModel: BaseModel]:
    """Immutable object-store write prepared before a SQLite transaction."""

    durable: TModel
    ref: str
    stored: StoredObject


class SQLiteRunCoverage:
    """Persist the contiguous logical-point prefix completed by a run."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def read(self) -> int:
        with self._runs.sqlite.read_transaction() as connection:
            return self.read_in_transaction(connection)

    def read_in_transaction(self, connection: sqlite3.Connection) -> int:
        row = _one(
            connection.execute(
                """
                SELECT completed_point_count
                FROM execution_coverage
                WHERE run_id = ?
                """,
                (self._run_id,),
            )
        )
        return 0 if row is None else _integer(row, "completed_point_count")

    def advance_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        start_index: int,
        point_count: int,
    ) -> tuple[int, bool]:
        """Advance one contiguous range or accept an already covered retry."""

        if start_index < 0 or point_count < 1:
            raise ExecutionJournalConflict("coverage range must be non-empty")
        completed = self.read_in_transaction(connection)
        end_index = start_index + point_count
        if end_index <= completed:
            return completed, False
        if start_index < completed:
            raise ExecutionJournalConflict(
                "coverage range partially overlaps the completed prefix"
            )
        if start_index > completed:
            raise ExecutionJournalConflict("coverage range is not the next prefix")
        connection.execute(
            """
            INSERT INTO execution_coverage(run_id, completed_point_count)
            VALUES (?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                completed_point_count = excluded.completed_point_count
            """,
            (self._run_id, end_index),
        )
        return end_index, True


class SQLiteRunPointLedger:
    """Persist dynamic point decisions and the final plan closure."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id

    def read(self) -> RunPointPlanView | None:
        with self._runs.sqlite.read_transaction() as connection:
            return self.read_in_transaction(connection)

    def read_in_transaction(
        self,
        connection: sqlite3.Connection,
    ) -> RunPointPlanView | None:
        row = _one(
            connection.execute(
                """
                SELECT initial_point_count, accepted_point_count, point_limit,
                       plan_closed, stop_reason,
                       (
                           SELECT COUNT(*)
                           FROM execution_domain_decisions AS decisions
                           WHERE decisions.run_id = execution_point_plans.run_id
                       ) AS decision_count,
                       (
                           SELECT COUNT(*)
                           FROM execution_domain_decisions AS decisions
                           WHERE decisions.run_id = execution_point_plans.run_id
                             AND json_extract(
                                 decisions.decision_json,
                                 '$.proposal.source'
                             ) = 'optimizer'
                       ) AS optimizer_attempt_count,
                       (
                           SELECT COUNT(*)
                           FROM execution_domain_queue AS requests
                           WHERE requests.run_id = execution_point_plans.run_id
                       ) AS operator_request_count
                FROM execution_point_plans
                WHERE run_id = ?
                """,
                (self._run_id,),
            )
        )
        if row is None:
            return None
        return RunPointPlanView(
            run_id=self._run_id,
            initial_point_count=_integer(row, "initial_point_count"),
            accepted_point_count=_integer(row, "accepted_point_count"),
            point_limit=_integer(row, "point_limit"),
            decision_count=_integer(row, "decision_count"),
            optimizer_attempt_count=_integer(row, "optimizer_attempt_count"),
            operator_request_count=_integer(row, "operator_request_count"),
            plan_closed=bool(_integer(row, "plan_closed")),
            stop_reason=(
                None if row["stop_reason"] is None else _text(row, "stop_reason")
            ),
        )

    def queue(self) -> RunDomainQueueView:
        with self._runs.sqlite.read_transaction() as connection:
            return self.queue_in_transaction(connection)

    def queue_in_transaction(
        self,
        connection: sqlite3.Connection,
    ) -> RunDomainQueueView:
        rows = _all(
            connection.execute(
                """
                SELECT entry_json
                FROM execution_domain_queue
                WHERE run_id = ?
                ORDER BY queue_index
                """,
                (self._run_id,),
            )
        )
        return RunDomainQueueView(
            run_id=self._run_id,
            items=tuple(
                RunDomainQueueEntryView.model_validate_json(_text(row, "entry_json"))
                for row in rows
            ),
        )

    def next_pending(self) -> RunDomainQueueEntryView | None:
        with self._runs.sqlite.read_transaction() as connection:
            row = _one(
                connection.execute(
                    """
                    SELECT entry_json
                    FROM execution_domain_queue
                    WHERE run_id = ? AND status = 'pending'
                    ORDER BY queue_index
                    LIMIT 1
                    """,
                    (self._run_id,),
                )
            )
        return (
            None
            if row is None
            else RunDomainQueueEntryView.model_validate_json(_text(row, "entry_json"))
        )

    def enqueue_in_transaction(
        self,
        connection: sqlite3.Connection,
        command: RunDomainEnqueueCommand,
        *,
        resolved_fragment: ResolvedDomainFragment,
        region_count: int,
    ) -> tuple[RunDomainQueueEntryView, bool]:
        request = command.domain_request(
            resolved_fragment,
            region_count=region_count,
        )
        existing = _one(
            connection.execute(
                """
                SELECT entry_json
                FROM execution_domain_queue
                WHERE run_id = ? AND request_id = ?
                """,
                (self._run_id, command.request_id),
            )
        )
        if existing is not None:
            entry = RunDomainQueueEntryView.model_validate_json(
                _text(existing, "entry_json")
            )
            if entry.request != request:
                raise ExecutionJournalConflict(
                    "operator domain request conflicts with durable state"
                )
            return entry, False
        plan = self.read_in_transaction(connection)
        if plan is None:
            raise ExecutionJournalConflict("point plan is not initialized")
        if plan.plan_closed:
            raise ExecutionJournalConflict("point plan is already closed")
        pending_count = sum(
            entry.request.request().total_point_count
            for entry in self.queue_in_transaction(connection).items
            if entry.status == "pending"
        )
        if (
            pending_count + request.request().total_point_count
            > plan.point_limit - plan.accepted_point_count
        ):
            raise ExecutionJournalConflict("domain queue exceeds the remaining budget")
        queue_index = _scalar_int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM execution_domain_queue
                WHERE run_id = ?
                """,
                (self._run_id,),
            )
        )
        entry = RunDomainQueueEntryView(
            queue_index=queue_index,
            occurred_at=datetime.now(UTC),
            request=request,
            status="pending",
        )
        connection.execute(
            """
            INSERT INTO execution_domain_queue(
                run_id, queue_index, request_id, status, entry_json
            )
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (
                self._run_id,
                entry.queue_index,
                entry.request.request_id,
                entry.model_dump_json(),
            ),
        )
        return entry, True

    def initialize_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        initial_point_count: int,
        point_limit: int,
        plan_closed: bool,
    ) -> RunPointPlanView:
        existing = _one(
            connection.execute(
                """
                SELECT initialize_operation_id, initial_point_count, point_limit,
                       plan_closed
                FROM execution_point_plans
                WHERE run_id = ?
                """,
                (self._run_id,),
            )
        )
        if existing is not None:
            if (
                _text(existing, "initialize_operation_id") != operation_id
                or _integer(existing, "initial_point_count") != initial_point_count
                or _integer(existing, "point_limit") != point_limit
                or bool(_integer(existing, "plan_closed")) != plan_closed
            ):
                raise ExecutionJournalConflict(
                    "point-plan initialization conflicts with durable state"
                )
            view = self.read_in_transaction(connection)
            assert view is not None
            return view
        stop_operation_id = f"{operation_id}.static" if plan_closed else None
        stop_reason = "static point plan" if plan_closed else None
        connection.execute(
            """
            INSERT INTO execution_point_plans(
                run_id, initialize_operation_id, initial_point_count,
                accepted_point_count, point_limit, plan_closed,
                stop_operation_id, stop_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._run_id,
                operation_id,
                initial_point_count,
                initial_point_count,
                point_limit,
                int(plan_closed),
                stop_operation_id,
                stop_reason,
            ),
        )
        view = self.read_in_transaction(connection)
        assert view is not None
        return view

    def append_decision_in_transaction(
        self,
        connection: sqlite3.Connection,
        command: RunDomainDecisionCommand,
    ) -> RunDomainDecisionView:
        existing = _one(
            connection.execute(
                """
                SELECT run_id, decision_json
                FROM execution_domain_decisions
                WHERE run_id = ? AND operation_id = ?
                """,
                (self._run_id, command.operation_id),
            )
        )
        if existing is not None:
            decision = RunDomainDecisionView.model_validate_json(
                _text(existing, "decision_json")
            )
            if (
                decision.proposal != command.proposal
                or decision.outcome != command.outcome
                or decision.accepted_point_start
                != _accepted_point_start(command.accepted_points)
                or decision.accepted_point_count != len(command.accepted_points)
                or self._decision_points_in_transaction(
                    connection,
                    command.operation_id,
                )
                != command.accepted_points
                or decision.reason != command.reason
                or decision.operator_request_id != command.operator_request_id
            ):
                raise ExecutionJournalConflict(
                    "point decision operation conflicts with durable state"
                )
            return decision
        plan = self.read_in_transaction(connection)
        if plan is None:
            raise ExecutionJournalConflict("point plan is not initialized")
        if plan.plan_closed:
            raise ExecutionJournalConflict("point plan is already closed")
        queued_entry = self._queued_entry_for_decision_in_transaction(
            connection,
            command,
        )
        accepted_points = command.accepted_points
        if command.outcome == "accepted":
            if plan.accepted_point_count + len(accepted_points) > plan.point_limit:
                raise ExecutionJournalConflict(
                    "domain decision exceeds the point budget"
                )
            if tuple(point.point_index for point in accepted_points) != tuple(
                range(
                    plan.accepted_point_count,
                    plan.accepted_point_count + len(accepted_points),
                )
            ):
                raise ExecutionJournalConflict(
                    "accepted domain points must extend the durable point prefix"
                )
            if any(
                point.domain_proposal_fingerprint
                != command.proposal.proposal_fingerprint
                for point in accepted_points
            ):
                raise ExecutionJournalConflict(
                    "accepted points do not match their domain proposal"
                )
        decision = RunDomainDecisionView(
            operation_id=command.operation_id,
            operator_request_id=command.operator_request_id,
            proposal_index=plan.decision_count,
            occurred_at=datetime.now(UTC),
            proposal=command.proposal,
            outcome=command.outcome,
            accepted_point_start=_accepted_point_start(accepted_points),
            accepted_point_count=len(accepted_points),
            reason=command.reason,
        )
        connection.execute(
            """
            INSERT INTO execution_domain_decisions(
                run_id, proposal_index, operation_id, decision_json
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                self._run_id,
                decision.proposal_index,
                decision.operation_id,
                decision.model_dump_json(),
            ),
        )
        if accepted_points:
            connection.executemany(
                """
                INSERT INTO execution_run_points(
                    run_id, point_index, decision_operation_id, point_json
                )
                VALUES (?, ?, ?, ?)
                """,
                tuple(
                    (
                        self._run_id,
                        accepted_point.point_index,
                        decision.operation_id,
                        accepted_point.model_dump_json(),
                    )
                    for accepted_point in accepted_points
                ),
            )
            connection.execute(
                """
                UPDATE execution_point_plans
                SET accepted_point_count = accepted_point_count + ?
                WHERE run_id = ?
                """,
                (len(accepted_points), self._run_id),
            )
        if queued_entry is not None:
            self._resolve_queue_entry_in_transaction(
                connection,
                queued_entry,
                decision,
            )
        return decision

    def _decision_points_in_transaction(
        self,
        connection: sqlite3.Connection,
        operation_id: str,
    ) -> tuple[AcceptedRunPointView, ...]:
        rows = _all(
            connection.execute(
                """
                SELECT point_json
                FROM execution_run_points
                WHERE run_id = ? AND decision_operation_id = ?
                ORDER BY point_index
                """,
                (self._run_id, operation_id),
            )
        )
        return tuple(
            AcceptedRunPointView.model_validate_json(_text(row, "point_json"))
            for row in rows
        )

    def _queued_entry_for_decision_in_transaction(
        self,
        connection: sqlite3.Connection,
        command: RunDomainDecisionCommand,
    ) -> RunDomainQueueEntryView | None:
        if command.operator_request_id is None:
            return None
        row = _one(
            connection.execute(
                """
                SELECT entry_json
                FROM execution_domain_queue
                WHERE run_id = ? AND request_id = ?
                """,
                (self._run_id, command.operator_request_id),
            )
        )
        if row is None:
            raise ExecutionJournalConflict("operator domain request does not exist")
        entry = RunDomainQueueEntryView.model_validate_json(_text(row, "entry_json"))
        if entry.status != "pending":
            raise ExecutionJournalConflict(
                "operator domain request is already resolved"
            )
        if entry.request.fragment != command.proposal.fragment:
            raise ExecutionJournalConflict(
                "domain proposal does not match its operator request"
            )
        return entry

    def _resolve_queue_entry_in_transaction(
        self,
        connection: sqlite3.Connection,
        entry: RunDomainQueueEntryView,
        decision: RunDomainDecisionView,
    ) -> None:
        resolved = RunDomainQueueEntryView(
            queue_index=entry.queue_index,
            occurred_at=entry.occurred_at,
            request=entry.request,
            status=decision.outcome,
            decision_operation_id=decision.operation_id,
            accepted_point_start=decision.accepted_point_start,
            accepted_point_count=decision.accepted_point_count,
            reason=decision.reason,
        )
        connection.execute(
            """
            UPDATE execution_domain_queue
            SET status = ?, decision_operation_id = ?, entry_json = ?
            WHERE run_id = ? AND request_id = ?
            """,
            (
                resolved.status,
                resolved.decision_operation_id,
                resolved.model_dump_json(),
                self._run_id,
                resolved.request.request_id,
            ),
        )

    def close_in_transaction(
        self,
        connection: sqlite3.Connection,
        command: RunPointPlanCloseCommand,
        *,
        completed_point_count: int,
    ) -> RunPointPlanView:
        row = _one(
            connection.execute(
                """
                SELECT stop_operation_id, stop_reason
                FROM execution_point_plans
                WHERE run_id = ?
                """,
                (self._run_id,),
            )
        )
        if row is None:
            raise ExecutionJournalConflict("point plan is not initialized")
        if row["stop_operation_id"] is not None:
            if (
                _text(row, "stop_operation_id") != command.operation_id
                or _text(row, "stop_reason") != command.reason
            ):
                raise ExecutionJournalConflict(
                    "point-plan closure conflicts with durable state"
                )
            view = self.read_in_transaction(connection)
            assert view is not None
            return view
        plan = self.read_in_transaction(connection)
        assert plan is not None
        if (
            command.based_on_completed_point_count != completed_point_count
            or completed_point_count != plan.accepted_point_count
        ):
            raise ExecutionJournalConflict(
                "point plan can close only at its durable accepted prefix"
            )
        connection.execute(
            """
            UPDATE execution_point_plans
            SET plan_closed = 1, stop_operation_id = ?, stop_reason = ?
            WHERE run_id = ?
            """,
            (command.operation_id, command.reason, self._run_id),
        )
        self._cancel_pending_queue_in_transaction(
            connection,
            reason=f"point plan closed: {command.reason}",
        )
        view = self.read_in_transaction(connection)
        assert view is not None
        return view

    def abandon_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        reason: str,
    ) -> RunPointPlanView | None:
        """Close an unfinished adaptive plan after a non-successful terminal result."""

        plan = self.read_in_transaction(connection)
        if plan is None or plan.plan_closed:
            return plan
        connection.execute(
            """
            UPDATE execution_point_plans
            SET plan_closed = 1, stop_operation_id = ?, stop_reason = ?
            WHERE run_id = ?
            """,
            (operation_id, reason, self._run_id),
        )
        self._cancel_pending_queue_in_transaction(
            connection,
            reason=f"point plan abandoned: {reason}",
        )
        view = self.read_in_transaction(connection)
        assert view is not None
        return view

    def _cancel_pending_queue_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        reason: str,
    ) -> None:
        pending = tuple(
            entry
            for entry in self.queue_in_transaction(connection).items
            if entry.status == "pending"
        )
        for entry in pending:
            cancelled = RunDomainQueueEntryView(
                queue_index=entry.queue_index,
                occurred_at=entry.occurred_at,
                request=entry.request,
                status="cancelled",
                reason=reason,
            )
            connection.execute(
                """
                UPDATE execution_domain_queue
                SET status = 'cancelled', entry_json = ?
                WHERE run_id = ? AND request_id = ?
                """,
                (
                    cancelled.model_dump_json(),
                    self._run_id,
                    cancelled.request.request_id,
                ),
            )


class SQLiteMeasurementDatasetRepository:
    """Append and seal canonical measurement ranges with database CAS."""

    def __init__(self, runs: SQLiteRunRepository, *, run_id: str) -> None:
        self._runs = runs
        self._run_id = run_id
        self._dataset_schema: MeasurementDatasetSchema | None = None
        self._dataset_schema_hash: str | None = None

    def prepare_header(
        self,
        header: MeasurementDatasetHeader,
    ) -> PreparedExecutionRecord[MeasurementDatasetHeader]:
        """Publish the immutable dataset contract before entering a transaction."""

        durable = header
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = f"{CANONICAL_MEASUREMENT_DATASET_REF}/header.json"
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_model(self._runs, durable),
        )

    def header_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[MeasurementDatasetHeader],
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish one canonical header or replay its exact durable value."""

        durable = prepared.durable
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT operation_id, content_hash
                    FROM execution_measurement_headers
                    WHERE run_id = ?
                    """,
                    (self._run_id,),
                )
            )
            if existing is not None:
                if (
                    _text(existing, "operation_id") != durable.operation_id
                    or _text(existing, "content_hash") != durable.content_hash
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset header already has different content"
                    )
                self._remember_measurement_schema(durable.dataset_schema)
                return _header_receipt(durable), False
            if _measurement_rows(connection, self._run_id) or _dataset_sealed(
                connection, self._run_id
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset content exists without its header"
                )
            _publish_ref(connection, self._run_id, prepared.ref, prepared.stored)
            connection.execute(
                """
                INSERT INTO execution_measurement_headers(
                    run_id, operation_id, content_hash,
                    contract_fingerprint, expected_record_count,
                    record_count_limit, ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.operation_id,
                    durable.content_hash,
                    durable.recording_contract_fingerprint,
                    durable.expected_record_count,
                    durable.record_count_limit,
                    prepared.ref,
                ),
            )
            self._remember_measurement_schema(durable.dataset_schema)
            return _header_receipt(durable), True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to initialize measurement dataset: {error}"
            ) from error

    def prepare_append(
        self,
        append: MeasurementDatasetAppend,
        *,
        dataset_schema: MeasurementDatasetSchema | None = None,
    ) -> PreparedExecutionRecord[MeasurementDatasetAppend]:
        """Publish immutable append content before entering the write transaction."""

        durable = append
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        ref = (
            f"{CANONICAL_MEASUREMENT_DATASET_REF}/chunks/"
            f"{durable.start_index:020d}.arrow"
        )
        schema_assets = (
            self._remember_measurement_schema(dataset_schema)
            if dataset_schema is not None
            else self._measurement_schema_assets()
        )
        if schema_assets is None:
            raise ExecutionJournalConflict(
                "measurement dataset append requires a registered schema"
            )
        selected_schema, selected_schema_hash = schema_assets
        return PreparedExecutionRecord(
            durable=durable,
            ref=ref,
            stored=_store_measurement_append(
                self._runs,
                durable,
                dataset_schema=selected_schema,
                dataset_schema_hash=selected_schema_hash,
            ),
        )

    def append_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedExecutionRecord[MeasurementDatasetAppend],
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish prepared append metadata in an existing transaction."""

        durable = prepared.durable
        ref = prepared.ref
        try:
            existing = _one(
                connection.execute(
                    """
                    SELECT operation_id, content_hash, ref
                    FROM execution_measurement_appends
                    WHERE run_id = ? AND start_index = ?
                    """,
                    (self._run_id, durable.start_index),
                )
            )
            if existing is not None:
                if (
                    _text(existing, "operation_id") != durable.operation_id
                    or _text(existing, "content_hash") != durable.content_hash
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset append already has different content"
                    )
                return (
                    MeasurementDatasetReceipt(
                        operation_id=_text(existing, "operation_id"),
                        dataset_content_hash=_text(existing, "content_hash"),
                    ),
                    False,
                )
            if _dataset_sealed(connection, self._run_id):
                raise ExecutionJournalConflict("measurement dataset is already sealed")
            header = _measurement_header_row(connection, self._run_id)
            if header is None:
                raise ExecutionJournalConflict(
                    "measurement dataset append requires a header"
                )
            if _text(header, "content_hash") != durable.header_content_hash:
                raise ExecutionJournalConflict(
                    "measurement dataset append references a different header"
                )
            record_count = _measurement_record_count(connection, self._run_id)
            if durable.start_index != record_count:
                raise ExecutionJournalConflict(
                    "measurement dataset append is not the next contiguous range"
                )
            if record_count + len(durable.records) > _integer(
                header, "record_count_limit"
            ):
                raise ExecutionJournalConflict(
                    "measurement dataset append exceeds its declared point count"
                )
            _publish_ref(connection, self._run_id, ref, prepared.stored)
            connection.execute(
                """
                INSERT INTO execution_measurement_appends(
                    run_id, start_index, operation_id,
                    content_hash, header_content_hash,
                    record_content_hashes_json, record_count,
                    ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._run_id,
                    durable.start_index,
                    durable.operation_id,
                    durable.content_hash,
                    durable.header_content_hash,
                    json.dumps(durable.record_content_hashes),
                    len(durable.records),
                    ref,
                ),
            )
            return _append_receipt(durable), True
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to append measurement dataset: {error}"
            ) from error

    def prepare_seal(
        self,
        seal: MeasurementDatasetSeal,
    ) -> MeasurementDatasetSeal:
        """Validate seal content before entering the write transaction."""

        durable = seal
        if durable.run_id != self._run_id:
            raise ExecutionJournalConflict(
                "measurement run_id does not match its execution repository"
            )
        return durable

    def seal_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: MeasurementDatasetSeal,
    ) -> tuple[MeasurementDatasetReceipt, bool]:
        """Publish prepared seal metadata in an existing transaction."""

        durable = prepared
        try:

            def commit_prepared() -> tuple[MeasurementDatasetReceipt, bool]:
                existing = _one(
                    connection.execute(
                        """
                        SELECT
                            operation_id,
                            content_hash,
                            dataset_content_hash
                        FROM execution_measurement_seals
                        WHERE run_id = ?
                        """,
                        (self._run_id,),
                    )
                )
                if existing is not None:
                    if (
                        _text(existing, "operation_id") != durable.operation_id
                        or _text(existing, "content_hash") != durable.content_hash
                    ):
                        raise ExecutionJournalConflict(
                            "measurement dataset seal already has different content"
                        )
                    return (
                        MeasurementDatasetReceipt(
                            operation_id=_text(existing, "operation_id"),
                            dataset_content_hash=_text(
                                existing,
                                "dataset_content_hash",
                            ),
                        ),
                        False,
                    )
                header = _measurement_header_row(connection, self._run_id)
                if header is None:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal requires a header"
                    )
                if _text(header, "content_hash") != durable.header_content_hash:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal references a different header"
                    )
                if durable.point_count > _integer(header, "record_count_limit"):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal exceeds its declared point count"
                    )
                appends = _measurement_rows(connection, self._run_id)
                if sum(_integer(row, "record_count") for row in appends) != (
                    durable.point_count
                ):
                    raise ExecutionJournalConflict(
                        "measurement dataset seal point count is incomplete"
                    )
                actual_hash = measurement_dataset_content_hash(
                    header_content_hash=durable.header_content_hash,
                    record_content_hashes=tuple(
                        record_hash
                        for row in appends
                        for record_hash in cast(
                            "list[str]",
                            json.loads(_text(row, "record_content_hashes_json")),
                        )
                    ),
                )
                if actual_hash != durable.dataset_content_hash:
                    raise ExecutionJournalConflict(
                        "measurement dataset seal content hash does not match appends"
                    )
                connection.execute(
                    """
                    INSERT INTO execution_measurement_seals(
                        run_id, operation_id, content_hash,
                        dataset_content_hash
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        self._run_id,
                        durable.operation_id,
                        durable.content_hash,
                        durable.dataset_content_hash,
                    ),
                )
                return _seal_receipt(durable), True

            return commit_prepared()
        except ExecutionJournalError:
            raise
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to seal measurement dataset: {error}"
            ) from error

    def measurements(
        self,
    ) -> tuple[MeasurementRecord, ...]:
        try:
            return tuple(
                self._runs.read_measurement_records(
                    self._run_id,
                    CANONICAL_MEASUREMENT_DATASET_REF,
                )
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset: {error}"
            ) from error

    def measurement_schema(self) -> MeasurementDatasetSchema | None:
        """Read the canonical schema without loading any measurement append."""

        if self._dataset_schema is not None:
            return self._dataset_schema
        try:
            with self._runs.sqlite.read_connection() as connection:
                header_row = _measurement_header_row(connection, self._run_id)
            if header_row is None:
                return None
            dataset_schema = self._runs.read_model(
                self._run_id,
                _text(header_row, "ref"),
                MeasurementDatasetHeader,
            ).dataset_schema
            self._remember_measurement_schema(dataset_schema)
            return dataset_schema
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset schema: {error}"
            ) from error

    def measurement_page(
        self,
        *,
        limit: int,
        offset: int,
        snapshot_size: int | None = None,
        include_schema: bool = True,
        variable_ids: Sequence[str] | None = None,
    ) -> tuple[
        tuple[MeasurementRecord, ...],
        int | None,
        MeasurementDatasetSchema | None,
        int,
    ]:
        """Read one record page against an append-stable finite snapshot.

        The first call may select the current append watermark; subsequent
        calls pass it back as ``snapshot_size`` so concurrent appends never
        extend the read. Storage is an ordered sequence of immutable Arrow IPC
        append blobs. Only blobs intersecting ``[offset, offset + limit)`` are
        opened, and ``variable_ids`` limits model decoding and transport even
        though one intersecting blob remains the physical I/O unit.
        """

        from scopecat.measurements.recording_arrow import (
            decode_measurement_record_slice,
        )

        try:
            with self._runs.sqlite.read_connection() as connection:
                total = _measurement_record_count(connection, self._run_id)
                selected_size = total if snapshot_size is None else snapshot_size
                if selected_size > total:
                    raise ValueError(
                        "measurement snapshot is larger than the available dataset"
                    )
                if offset > selected_size:
                    raise ValueError("measurement page offset exceeds its snapshot")
                page_end = min(offset + limit, selected_size)
                rows = _all(
                    connection.execute(
                        """
                        SELECT start_index, record_count, ref
                        FROM execution_measurement_appends
                        WHERE run_id = ?
                          AND start_index < ?
                          AND start_index + record_count > ?
                        ORDER BY start_index
                        """,
                        (self._run_id, page_end, offset),
                    )
                )
            schema_assets = self._measurement_schema_assets()
            if schema_assets is None:
                return (), None, None, selected_size
            dataset_schema, dataset_schema_hash = schema_assets
            items: list[MeasurementRecord] = []
            for row in rows:
                start_index = _integer(row, "start_index")
                chunk_start = max(0, offset - start_index)
                chunk_end = min(
                    _integer(row, "record_count"),
                    page_end - start_index,
                )
                items.extend(
                    decode_measurement_record_slice(
                        self._runs.read_bytes(
                            self._run_id,
                            _text(row, "ref"),
                        ),
                        dataset_schema,
                        offset=chunk_start,
                        length=chunk_end - chunk_start,
                        variable_ids=variable_ids,
                        dataset_schema_hash=dataset_schema_hash,
                    )
                )
            next_offset = (
                offset + len(items) if offset + len(items) < selected_size else None
            )
            return (
                tuple(items),
                next_offset,
                dataset_schema if include_schema else None,
                selected_size,
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset page: {error}"
            ) from error

    def measurement_record_count(self) -> int:
        """Read the current durable point-row count without opening append blobs."""

        try:
            with self._runs.sqlite.read_connection() as connection:
                return _measurement_record_count(connection, self._run_id)
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read measurement dataset size: {error}"
            ) from error

    def measurement_records_at(
        self,
        point_indices: tuple[int, ...],
        *,
        variable_ids: Sequence[str] | None = None,
    ) -> tuple[MeasurementRecord, ...]:
        """Read selected point indices from intersecting Arrow record batches."""

        from scopecat.measurements.recording_arrow import (
            decode_measurement_record_indices,
        )

        selected = tuple(sorted(set(point_indices)))
        try:
            with self._runs.sqlite.read_connection() as connection:
                rows = _measurement_rows(connection, self._run_id)
            schema_assets = self._measurement_schema_assets()
            if schema_assets is None:
                return ()
            dataset_schema, dataset_schema_hash = schema_assets
            records_by_index: dict[int, MeasurementRecord] = {}
            for row in rows:
                start = _integer(row, "start_index")
                end = start + _integer(row, "record_count")
                first = bisect_left(selected, start)
                last = bisect_left(selected, end)
                if first == last:
                    continue
                local_indices = tuple(
                    point_index - start for point_index in selected[first:last]
                )
                records = decode_measurement_record_indices(
                    self._runs.read_bytes(
                        self._run_id,
                        _text(row, "ref"),
                    ),
                    dataset_schema,
                    local_indices,
                    variable_ids=variable_ids,
                    dataset_schema_hash=dataset_schema_hash,
                )
                records_by_index.update(zip(selected[first:last], records, strict=True))
            return tuple(
                records_by_index[point_index]
                for point_index in point_indices
                if point_index in records_by_index
            )
        except Exception as error:
            raise ExecutionJournalError(
                f"failed to read selected measurement records: {error}"
            ) from error

    def _measurement_schema_assets(
        self,
    ) -> tuple[MeasurementDatasetSchema, str] | None:
        dataset_schema = self.measurement_schema()
        if dataset_schema is None:
            return None
        assert self._dataset_schema_hash is not None
        return dataset_schema, self._dataset_schema_hash

    def _remember_measurement_schema(
        self,
        dataset_schema: MeasurementDatasetSchema,
    ) -> tuple[MeasurementDatasetSchema, str]:
        if dataset_schema != self._dataset_schema:
            from scopecat.measurements.recording_arrow import (
                measurement_dataset_schema_hash,
            )

            self._dataset_schema = dataset_schema
            self._dataset_schema_hash = measurement_dataset_schema_hash(dataset_schema)
        assert self._dataset_schema_hash is not None
        return dataset_schema, self._dataset_schema_hash


def _header_receipt(
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=header.operation_id,
        dataset_content_hash=header.content_hash,
    )


def _append_receipt(
    append: MeasurementDatasetAppend,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=append.operation_id,
        dataset_content_hash=append.content_hash,
    )


def _seal_receipt(
    seal: MeasurementDatasetSeal,
) -> MeasurementDatasetReceipt:
    return MeasurementDatasetReceipt(
        operation_id=seal.operation_id,
        dataset_content_hash=seal.dataset_content_hash,
    )


def _dataset_sealed(
    connection: sqlite3.Connection,
    run_id: str,
) -> bool:
    return (
        _one(
            connection.execute(
                """
                SELECT 1 AS sealed FROM execution_measurement_seals
                WHERE run_id = ?
                """,
                (run_id,),
            )
        )
        is not None
    )


def _measurement_rows(
    connection: sqlite3.Connection,
    run_id: str,
) -> list[sqlite3.Row]:
    return _all(
        connection.execute(
            """
            SELECT * FROM execution_measurement_appends
            WHERE run_id = ?
            ORDER BY start_index
            """,
            (run_id,),
        )
    )


def _measurement_header_row(
    connection: sqlite3.Connection,
    run_id: str,
) -> sqlite3.Row | None:
    return _one(
        connection.execute(
            """
            SELECT * FROM execution_measurement_headers
            WHERE run_id = ?
            """,
            (run_id,),
        )
    )


def _measurement_record_count(
    connection: sqlite3.Connection,
    run_id: str,
) -> int:
    row = _one(
        connection.execute(
            """
            SELECT COALESCE(SUM(record_count), 0) AS record_count
            FROM execution_measurement_appends
            WHERE run_id = ?
            """,
            (run_id,),
        )
    )
    assert row is not None
    return _integer(row, "record_count")


def _store_model(runs: SQLiteRunRepository, model: BaseModel) -> StoredObject:
    try:
        content = (
            json.dumps(
                model.model_dump(mode="json"),
                allow_nan=True,
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        return runs.objects.put(content)
    except (
        ObjectStoreError,
        PydanticSerializationError,
        TypeError,
        ValueError,
    ) as error:
        raise ExecutionJournalError(
            f"execution record is not durably serializable: {error}"
        ) from error


def _store_measurement_append(
    runs: SQLiteRunRepository,
    append: MeasurementDatasetAppend,
    *,
    dataset_schema: MeasurementDatasetSchema,
    dataset_schema_hash: str,
) -> StoredObject:
    from scopecat.measurements.recording_arrow import (
        MeasurementArrowCodecError,
        encode_measurement_append,
    )

    try:
        return runs.objects.put(
            encode_measurement_append(
                append,
                dataset_schema,
                dataset_schema_hash=dataset_schema_hash,
            )
        )
    except (MeasurementArrowCodecError, ObjectStoreError) as error:
        raise ExecutionJournalError(
            f"measurement append is not durably serializable: {error}"
        ) from error


def _publish_ref(
    connection: sqlite3.Connection,
    run_id: str,
    ref: str,
    stored: StoredObject,
) -> None:
    connection.execute(
        """
        INSERT INTO run_repository_refs(run_id, ref, digest)
        VALUES (?, ?, ?)
        ON CONFLICT(run_id, ref) DO UPDATE SET
            digest = excluded.digest
        """,
        (run_id, ref, stored.digest),
    )


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _scalar_int(cursor: sqlite3.Cursor) -> int:
    row = _one(cursor)
    assert row is not None
    return cast("int", row[0])


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])


def _accepted_point_start(points: tuple[AcceptedRunPointView, ...]) -> int | None:
    return None if not points else points[0].point_index
