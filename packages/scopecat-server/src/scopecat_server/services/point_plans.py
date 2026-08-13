"""Application service for durable run point-plan state."""

from __future__ import annotations

import sqlite3

from scopecat.control.models import ControlRun, DurableEventInput
from scopecat.daemon.points import (
    RunPointDecisionCommand,
    RunPointDecisionView,
    RunPointEnqueueCommand,
    RunPointPlanCloseCommand,
    RunPointPlanView,
    RunPointQueueEntryView,
    RunPointQueueView,
)

from scopecat_server.storage.sqlite.control_plane import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    SQLiteControlPlane,
)
from scopecat_server.storage.sqlite.execution import (
    ExecutionJournalConflict,
    SQLiteRunPointLedger,
)
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

from ..errors import BackendConflict, BackendNotFound

_POINT_PLAN_ADMISSION_OPERATION_ID = "point-plan.admission.v1"


class RunPointPlanService:
    """Own point-plan admission, decisions, queueing, and closure."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
    ) -> None:
        self._control = control
        self._runs = runs

    def initialize_admitted_in_transaction(
        self,
        connection: sqlite3.Connection,
        run: ControlRun,
    ) -> RunPointPlanView:
        plan = run.admission.plan
        return self._ledger(run.run_id).initialize_in_transaction(
            connection,
            operation_id=_POINT_PLAN_ADMISSION_OPERATION_ID,
            initial_point_count=plan.initial_point_count,
            point_limit=plan.point_limit,
            plan_closed=plan.point_count is not None,
        )

    def read(self, run_id: str) -> RunPointPlanView:
        self._require_run(run_id)
        plan = self._ledger(run_id).read()
        assert plan is not None, "admitted run is missing its point plan"
        return plan

    def read_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> RunPointPlanView:
        plan = self._ledger(run_id).read_in_transaction(connection)
        assert plan is not None, "admitted run is missing its point plan"
        return plan

    def queue(self, run_id: str) -> RunPointQueueView:
        self._require_run(run_id)
        return self._ledger(run_id).queue()

    def next_queued(self, run_id: str) -> RunPointQueueView:
        self._require_run(run_id)
        entry = self._ledger(run_id).next_pending()
        return RunPointQueueView(
            run_id=run_id,
            items=() if entry is None else (entry,),
        )

    def enqueue(
        self,
        run_id: str,
        command: RunPointEnqueueCommand,
    ) -> RunPointQueueEntryView:
        try:
            with self._control.write_transaction() as connection:
                run = self._control.get_run_in_transaction(connection, run_id)
                if run.state != "leased":
                    raise ControlPlaneConflict(
                        "operator points can be queued only while a run is active"
                    )
                if set(command.coordinates) != set(run.admission.plan.coordinate_ids):
                    raise ControlPlaneConflict(
                        "queued point coordinates do not match the admitted axes"
                    )
                entry, created = self._ledger(run_id).enqueue_in_transaction(
                    connection,
                    command,
                )
                if created:
                    self._control.append_event_in_transaction(
                        connection,
                        DurableEventInput(
                            run_id=run_id,
                            kind="operator_point_requested",
                            payload={
                                "queue_index": entry.queue_index,
                                "request_id": entry.request.request_id,
                            },
                        ),
                    )
                return entry
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except (ControlPlaneConflict, ExecutionJournalConflict) as error:
            raise BackendConflict(str(error)) from error

    def append_decision_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        command: RunPointDecisionCommand,
        *,
        completed_point_count: int,
    ) -> RunPointDecisionView:
        return self._ledger(run_id).append_decision_in_transaction(
            connection,
            command,
            completed_point_count=completed_point_count,
        )

    def close_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        command: RunPointPlanCloseCommand,
        *,
        completed_point_count: int,
    ) -> RunPointPlanView:
        return self._ledger(run_id).close_in_transaction(
            connection,
            command,
            completed_point_count=completed_point_count,
        )

    def abandon_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        operation_id: str,
        reason: str,
    ) -> RunPointPlanView:
        plan = self._ledger(run_id).abandon_in_transaction(
            connection,
            operation_id=operation_id,
            reason=reason,
        )
        assert plan is not None, "admitted run is missing its point plan"
        return plan

    def _ledger(self, run_id: str) -> SQLiteRunPointLedger:
        return SQLiteRunPointLedger(self._runs, run_id=run_id)

    def _require_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error


__all__ = ["RunPointPlanService"]
