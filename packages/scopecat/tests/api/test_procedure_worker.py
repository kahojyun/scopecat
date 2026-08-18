from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from types import SimpleNamespace
from typing import cast

import httpx2
import pytest
from pydantic import BaseModel, ConfigDict

from scopecat.api._config import LabConfigOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.calibration_finalizer import (
    CalibrationPublicationFinalizerCycleResult,
)
from scopecat.api.calibration_planner import CalibrationEvaluatorCycleResult
from scopecat.api.calibration_publication import (
    CalibrationCohortPublicationPlan,
    CalibrationPublicationDriftError,
    CalibrationPublicationOutcomeUnknown,
)
from scopecat.api.procedure_planner import ProcedurePlannerCycleResult
from scopecat.api.procedure_worker import ProjectProcedureWorkerLoop
from scopecat.api.procedures import (
    LabProcedureOperations,
    ProcedureHandle,
    ProcedureLabSession,
)
from scopecat.automation import (
    ProcedureControlError,
    ProcedureDefinitionRef,
    ProcedureIntent,
    ProcedureLeaseLostError,
    ProcedureRegistry,
    ProcedureRun,
    ProcedureRunnablePage,
    ProcedureRunnableQuery,
    ProcedureSchedule,
    ProcedureScheduleCancelCommand,
    ProcedureScheduleCancellation,
    ProcedureScheduleCancelReceipt,
    ProcedureScheduleCreateCommand,
    ProcedureScheduleCreateReceipt,
    ProcedureScheduleDuePage,
    ProcedureScheduleDueQuery,
    ProcedureScheduleListQuery,
    ProcedureScheduleMaterialization,
    ProcedureScheduleMaterializeCommand,
    ProcedureScheduleMaterializeReceipt,
    ProcedureSchedulePage,
    ProcedureScheduleRegistry,
    ProcedureScheduleState,
    ProcedureWorkerLease,
    procedure,
    procedure_intent_hash,
    procedure_schedule_request_key,
)
from scopecat.daemon.client import (
    DaemonClient,
    DaemonConflictError,
    DaemonNotFoundError,
    DaemonUnavailableError,
)

_CREATED_AT = datetime(2026, 8, 18, 8, tzinfo=UTC)
_DUE_AT = _CREATED_AT + timedelta(hours=1)
_TERMINAL_AT = _DUE_AT + timedelta(minutes=1)


class ScheduledIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: int


@procedure(id="tests.scheduled", version="1", intent=ScheduledIntent)
def SCHEDULED(_context: object, _intent: ScheduledIntent) -> None:
    pass


@dataclass(slots=True)
class _FakeWorkerOperations:
    due_page: ProcedureScheduleDuePage
    runnable_page: ProcedureRunnablePage
    calls: list[tuple[object, ...]] = field(default_factory=list, init=False)
    materialize_errors: dict[str, Exception] = field(default_factory=dict, init=False)
    resume_errors: dict[str, Exception] = field(default_factory=dict, init=False)
    schedule_observations: dict[str, ProcedureSchedule] = field(
        default_factory=dict,
        init=False,
    )
    schedule_lookup_errors: dict[str, Exception] = field(
        default_factory=dict,
        init=False,
    )
    due_pages: dict[tuple[int | None, int | None], ProcedureScheduleDuePage] = field(
        default_factory=dict,
        init=False,
    )
    stop_after_materialize: Event | None = field(default=None, init=False)
    stop_after_resume: Event | None = field(default=None, init=False)
    yield_callbacks: list[Callable[[], bool] | None] = field(
        default_factory=list,
        init=False,
    )
    due_error: Exception | None = field(default=None, init=False)
    cycle_called: Event = field(default_factory=Event, init=False)

    def list_due_schedules(
        self,
        *,
        limit: int = 50,
        cursor: int | None = None,
        through_sequence: int | None = None,
    ) -> ProcedureScheduleDuePage:
        self.calls.append(("due", limit, cursor, through_sequence))
        self.cycle_called.set()
        if self.due_error is not None:
            raise self.due_error
        return self.due_pages.get((cursor, through_sequence), self.due_page)

    def get_schedule(self, schedule_id: str) -> ProcedureSchedule:
        self.calls.append(("get_schedule", schedule_id))
        error = self.schedule_lookup_errors.get(schedule_id)
        if error is not None:
            raise error
        return self.schedule_observations.get(
            schedule_id,
            _schedule(schedule_id, state="materialized"),
        )

    def materialize_schedule(
        self,
        schedule_id: str,
        *,
        expected_revision: int,
    ) -> ProcedureSchedule:
        self.calls.append(("materialize", schedule_id, expected_revision))
        error = self.materialize_errors.get(schedule_id)
        if error is not None:
            raise error
        if self.stop_after_materialize is not None:
            self.stop_after_materialize.set()
            self.stop_after_materialize = None
        return _schedule(schedule_id)

    def list_runnable(self, *, limit: int = 50) -> ProcedureRunnablePage:
        self.calls.append(("runnable", limit))
        return self.runnable_page

    def resume_snapshot(
        self,
        run: ProcedureRun,
        *,
        worker_id: str | None = None,
        should_yield: Callable[[], bool] | None = None,
    ) -> ProcedureHandle:
        assert should_yield is None or callable(should_yield)
        self.yield_callbacks.append(should_yield)
        self.calls.append(("resume_snapshot", run.procedure_run_id, worker_id))
        error = self.resume_errors.get(run.procedure_run_id)
        if error is not None:
            raise error
        if self.stop_after_resume is not None:
            self.stop_after_resume.set()
            self.stop_after_resume = None
        return ProcedureHandle(
            cast("LabProcedureOperations", cast("object", self)),
            run.procedure_run_id,
        )


class _ScheduleClient:
    def __init__(self) -> None:
        self.create_commands: list[ProcedureScheduleCreateCommand] = []
        self.list_queries: list[ProcedureScheduleListQuery] = []
        self.due_queries: list[ProcedureScheduleDueQuery] = []
        self.cancel_commands: list[ProcedureScheduleCancelCommand] = []
        self.materialize_commands: list[ProcedureScheduleMaterializeCommand] = []
        self.runnable_queries: list[ProcedureRunnableQuery] = []

    def create_procedure_schedule(
        self,
        command: ProcedureScheduleCreateCommand,
    ) -> ProcedureScheduleCreateReceipt:
        self.create_commands.append(command)
        return ProcedureScheduleCreateReceipt(
            schedule=_schedule(
                command.schedule_id,
                definition=command.definition,
                intent=command.intent,
                due_at=command.due_at,
            )
        )

    def get_procedure_schedule(self, schedule_id: str) -> ProcedureSchedule:
        return _schedule(schedule_id)

    def list_procedure_schedules(
        self,
        query: ProcedureScheduleListQuery,
    ) -> ProcedureSchedulePage:
        self.list_queries.append(query)
        return ProcedureSchedulePage(items=(_schedule("listed"),))

    def list_due_procedure_schedules(
        self,
        query: ProcedureScheduleDueQuery,
    ) -> ProcedureScheduleDuePage:
        self.due_queries.append(query)
        return ProcedureScheduleDuePage(items=(_schedule("due"),))

    def cancel_procedure_schedule(
        self,
        command: ProcedureScheduleCancelCommand,
    ) -> ProcedureScheduleCancelReceipt:
        self.cancel_commands.append(command)
        return ProcedureScheduleCancelReceipt(
            schedule=_schedule(
                command.schedule_id,
                state="cancelled",
                actor=command.actor,
                reason=command.reason,
            )
        )

    def materialize_procedure_schedule(
        self,
        command: ProcedureScheduleMaterializeCommand,
    ) -> ProcedureScheduleMaterializeReceipt:
        self.materialize_commands.append(command)
        return ProcedureScheduleMaterializeReceipt(
            schedule=_schedule(command.schedule_id, state="materialized")
        )

    def list_runnable_procedures(
        self,
        query: ProcedureRunnableQuery,
    ) -> ProcedureRunnablePage:
        self.runnable_queries.append(query)
        return ProcedureRunnablePage()


@dataclass(slots=True)
class _FakePlanner:
    calls: list[tuple[object, ...]]
    result: ProcedurePlannerCycleResult

    def cycle(self, stop: Event | None = None) -> ProcedurePlannerCycleResult:
        self.calls.append(("plan", stop))
        return self.result


@dataclass(slots=True)
class _FakeCalibrationEvaluator:
    calls: list[tuple[object, ...]]
    result: CalibrationEvaluatorCycleResult

    def cycle(self, stop: Event | None = None) -> CalibrationEvaluatorCycleResult:
        self.calls.append(("calibrate", stop))
        return self.result


@dataclass(slots=True)
class _FakeCalibrationFinalizer:
    calls: list[tuple[object, ...]]
    result: CalibrationPublicationFinalizerCycleResult
    error: Exception | None = None
    stop_after_cycle: Event | None = None

    def cycle(
        self,
        stop: Event | None = None,
    ) -> CalibrationPublicationFinalizerCycleResult:
        self.calls.append(("finalize", stop))
        if self.error is not None:
            raise self.error
        if self.stop_after_cycle is not None:
            self.stop_after_cycle.set()
            self.stop_after_cycle = None
        return self.result


def _publication_result() -> CalibrationPublicationFinalizerCycleResult:
    return CalibrationPublicationFinalizerCycleResult(
        ready_items=0,
        prepared_items=0,
        published_items=0,
        deferred_items=0,
        attention_items=0,
        reconciled_items=0,
        superseded_items=0,
        benign_races=0,
        failures=0,
        has_more=False,
    )


def _planner_result() -> ProcedurePlannerCycleResult:
    return ProcedurePlannerCycleResult(
        definitions=0,
        eligible_occurrences=0,
        existing_schedules=0,
        created_schedules=0,
        reconciled_schedules=0,
        drifted_schedules=0,
        failures=0,
        has_more=False,
    )


def _calibration_result() -> CalibrationEvaluatorCycleResult:
    return CalibrationEvaluatorCycleResult(
        definitions=0,
        selected_targets=0,
        fresh_members=0,
        pending_publication_members=0,
        blocked_members=0,
        suppressed_active_members=0,
        suppressed_failed_members=0,
        suppressed_attention_members=0,
        ready_members=0,
        admitted_members=0,
        created_cohorts=0,
        reconciled_cohorts=0,
        admission_conflicts=0,
        cohort_drifts=0,
        failures=0,
        has_more=False,
    )


def test_cycle_finalizes_before_config_sensitive_planning() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    finalizer = _FakeCalibrationFinalizer(
        operations.calls,
        replace(
            _publication_result(),
            ready_items=1,
            prepared_items=1,
            published_items=1,
        ),
    )
    planner = _FakePlanner(operations.calls, _planner_result())
    evaluator = _FakeCalibrationEvaluator(
        operations.calls,
        _calibration_result(),
    )

    result = ProjectProcedureWorkerLoop(
        operations,
        calibration_finalizer=finalizer,
        planner=planner,
        calibration_evaluator=evaluator,
    ).cycle()

    assert result.ready_calibration_publications == 1
    assert result.prepared_calibration_publications == 1
    assert result.published_calibration_publications == 1
    assert result.calibration_publication_barrier is False
    assert operations.calls == [
        ("finalize", None),
        ("plan", None),
        ("calibrate", None),
        ("due", 50, None, None),
        ("runnable", 50),
    ]


def test_publication_backlog_blocks_new_planning_but_drains_frozen_work() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(items=(_schedule("already-due"),)),
        ProcedureRunnablePage(items=(_run("already-runnable"),)),
    )
    finalizer = _FakeCalibrationFinalizer(
        operations.calls,
        replace(
            _publication_result(),
            ready_items=1,
            deferred_items=1,
            benign_races=1,
            has_more=True,
        ),
    )
    planner = _FakePlanner(operations.calls, _planner_result())
    evaluator = _FakeCalibrationEvaluator(
        operations.calls,
        _calibration_result(),
    )

    result = ProjectProcedureWorkerLoop(
        operations,
        calibration_finalizer=finalizer,
        planner=planner,
        calibration_evaluator=evaluator,
        worker_id="worker-publication-barrier",
    ).cycle()

    assert result.calibration_publication_barrier is True
    assert result.deferred_calibration_publications == 1
    assert result.calibration_publication_races == 1
    assert result.eligible_interval_occurrences == 0
    assert result.selected_calibration_targets == 0
    assert result.materialized_schedules == 1
    assert result.dispatched_procedures == 1
    assert result.has_more is True
    assert operations.calls == [
        ("finalize", None),
        ("due", 50, None, None),
        ("materialize", "already-due", 1),
        ("runnable", 50),
        (
            "resume_snapshot",
            "already-runnable",
            "worker-publication-barrier",
        ),
    ]


def test_stop_after_finalizer_prevents_every_later_worker_phase() -> None:
    stop = Event()
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    finalizer = _FakeCalibrationFinalizer(
        operations.calls,
        _publication_result(),
        stop_after_cycle=stop,
    )

    result = ProjectProcedureWorkerLoop(
        operations,
        calibration_finalizer=finalizer,
        planner=_FakePlanner(operations.calls, _planner_result()),
        calibration_evaluator=_FakeCalibrationEvaluator(
            operations.calls,
            _calibration_result(),
        ),
    ).cycle(stop)

    assert result.has_more is False
    assert operations.calls == [("finalize", stop)]


def test_cycle_plans_before_due_work_and_surfaces_planner_drift() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    planner = _FakePlanner(
        operations.calls,
        ProcedurePlannerCycleResult(
            definitions=2,
            eligible_occurrences=2,
            existing_schedules=1,
            created_schedules=1,
            reconciled_schedules=0,
            drifted_schedules=1,
            failures=2,
            has_more=False,
        ),
    )

    result = ProjectProcedureWorkerLoop(operations, planner=planner).cycle()

    assert result.eligible_interval_occurrences == 2
    assert result.created_interval_schedules == 1
    assert result.existing_interval_schedules == 1
    assert result.reconciled_interval_schedules == 0
    assert result.interval_schedule_drifts == 1
    assert result.planner_failures == 2
    assert operations.calls == [
        ("plan", None),
        ("due", 50, None, None),
        ("runnable", 50),
    ]


def test_cycle_admits_calibration_frontier_before_due_work() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    evaluator = _FakeCalibrationEvaluator(
        operations.calls,
        CalibrationEvaluatorCycleResult(
            definitions=1,
            selected_targets=3,
            fresh_members=1,
            pending_publication_members=0,
            blocked_members=1,
            suppressed_active_members=0,
            suppressed_failed_members=0,
            suppressed_attention_members=0,
            ready_members=1,
            admitted_members=1,
            created_cohorts=1,
            reconciled_cohorts=0,
            admission_conflicts=0,
            cohort_drifts=0,
            failures=0,
            has_more=False,
        ),
    )

    result = ProjectProcedureWorkerLoop(
        operations,
        calibration_evaluator=evaluator,
    ).cycle()

    assert result.selected_calibration_targets == 3
    assert result.fresh_calibrations == 1
    assert result.blocked_calibrations == 1
    assert result.admitted_calibrations == 1
    assert result.created_calibration_cohorts == 1
    assert operations.calls == [
        ("calibrate", None),
        ("due", 50, None, None),
        ("runnable", 50),
    ]


def test_cycle_materializes_before_dispatch_and_continues_known_races() -> None:
    first_schedule = _schedule("schedule-1")
    second_schedule = _schedule("schedule-2")
    first_run = _run("run-1")
    second_run = _run("run-2")
    third_run = _run("run-3")
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(
            items=(first_schedule, second_schedule),
            next_cursor=2,
            through_sequence=20,
        ),
        ProcedureRunnablePage(items=(first_run, second_run, third_run)),
    )
    operations.materialize_errors["schedule-2"] = _conflict("schedule raced")
    operations.resume_errors["run-2"] = ProcedureControlError(
        "acquire_procedure_worker_lease",
        _conflict("lease raced"),
    )
    operations.resume_errors["run-3"] = ValueError("known procedure failure")
    loop = ProjectProcedureWorkerLoop(
        operations,
        worker_id="worker-exact",
        schedule_limit=2,
        runnable_limit=3,
    )

    result = loop.cycle()

    assert result.due_schedules == 2
    assert result.materialized_schedules == 1
    assert result.schedule_conflicts == 1
    assert result.schedule_failures == 0
    assert result.runnable_procedures == 3
    assert result.dispatched_procedures == 1
    assert result.procedure_failures == 1
    assert result.procedure_conflicts == 0
    assert result.lease_conflicts == 1
    assert result.has_more is True
    assert operations.calls == [
        ("due", 2, None, None),
        ("materialize", "schedule-1", 1),
        ("materialize", "schedule-2", 1),
        ("get_schedule", "schedule-2"),
        ("runnable", 3),
        ("resume_snapshot", "run-1", "worker-exact"),
        ("resume_snapshot", "run-2", "worker-exact"),
        ("resume_snapshot", "run-3", "worker-exact"),
    ]


def test_schedule_conflict_requires_an_exact_terminal_or_revision_race() -> None:
    unchanged = _schedule("schedule-unchanged")
    changed = _schedule("schedule-changed")
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(items=(unchanged, changed)),
        ProcedureRunnablePage(),
    )
    operations.materialize_errors[unchanged.schedule_id] = _conflict(
        "unexplained conflict"
    )
    operations.materialize_errors[changed.schedule_id] = _conflict("terminal race")
    operations.schedule_observations[unchanged.schedule_id] = unchanged
    operations.schedule_observations[changed.schedule_id] = _schedule(
        changed.schedule_id,
        state="cancelled",
    )

    result = ProjectProcedureWorkerLoop(operations).cycle()

    assert result.schedule_failures == 1
    assert result.schedule_conflicts == 1
    assert result.materialized_schedules == 0


def test_deterministic_procedure_control_errors_are_local_conflicts() -> None:
    control_conflict = _run("run-control-conflict")
    acquire_conflict = _run("run-acquire-conflict")
    lost_lease = _run("run-lost-lease")
    successful = _run("run-successful")
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(
            items=(control_conflict, acquire_conflict, lost_lease, successful)
        ),
    )
    operations.resume_errors[control_conflict.procedure_run_id] = ProcedureControlError(
        "begin_procedure_step", _not_found("run disappeared")
    )
    operations.resume_errors[acquire_conflict.procedure_run_id] = ProcedureControlError(
        "acquire_procedure_worker_lease",
        _conflict("lease raced"),
    )
    operations.resume_errors[lost_lease.procedure_run_id] = ProcedureLeaseLostError(
        _lease(lost_lease.procedure_run_id),
        _conflict("lease was fenced"),
    )

    result = ProjectProcedureWorkerLoop(operations).cycle()

    assert result.procedure_conflicts == 1
    assert result.lease_conflicts == 2
    assert result.dispatched_procedures == 1
    assert result.procedure_failures == 0


@pytest.mark.parametrize("status", [404, 422])
def test_non_conflict_acquire_error_is_fatal_and_lease_error_is_not_benign(
    status: int,
) -> None:
    acquire = _run(f"run-acquire-{status}")
    lost = _run(f"run-lost-{status}")
    acquire_operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(items=(acquire,)),
    )
    cause = (
        _not_found("authority missing")
        if status == 404
        else _http_status(status, "authority rejected")
    )
    acquire_operations.resume_errors[acquire.procedure_run_id] = ProcedureControlError(
        "acquire_procedure_worker_lease",
        cause,
    )

    with pytest.raises(ProcedureControlError):
        ProjectProcedureWorkerLoop(acquire_operations).cycle()

    lease_operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(items=(lost,)),
    )
    lease_operations.resume_errors[lost.procedure_run_id] = ProcedureLeaseLostError(
        _lease(lost.procedure_run_id),
        cause,
    )

    result = ProjectProcedureWorkerLoop(lease_operations).cycle()

    assert result.procedure_conflicts == 1
    assert result.lease_conflicts == 0


def test_due_cursor_is_preserved_across_bounded_cycles_and_then_reset() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    operations.due_pages[(None, None)] = ProcedureScheduleDuePage(
        items=(_schedule("schedule-first-page"),),
        next_cursor=10,
        through_sequence=20,
    )
    operations.due_pages[(10, 20)] = ProcedureScheduleDuePage(
        items=(_schedule("schedule-last-page"),),
    )
    loop = ProjectProcedureWorkerLoop(operations)

    assert loop.cycle().has_more is True
    assert loop.cycle().has_more is False
    loop.cycle()

    due_calls = [call for call in operations.calls if call[0] == "due"]
    assert due_calls == [
        ("due", 50, None, None),
        ("due", 50, 10, 20),
        ("due", 50, None, None),
    ]


def test_stop_halfway_through_due_page_does_not_advance_traversal() -> None:
    stop = Event()
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(
            items=(_schedule("schedule-1"), _schedule("schedule-2")),
            next_cursor=10,
            through_sequence=20,
        ),
        ProcedureRunnablePage(),
    )
    operations.stop_after_materialize = stop
    loop = ProjectProcedureWorkerLoop(operations)

    interrupted = loop.cycle(stop)
    stop.clear()
    resumed = loop.cycle(stop)

    assert interrupted.materialized_schedules == 1
    assert interrupted.has_more is True
    assert resumed.materialized_schedules == 2
    due_calls = [call for call in operations.calls if call[0] == "due"]
    assert due_calls == [
        ("due", 50, None, None),
        ("due", 50, None, None),
    ]


def test_worker_ids_are_unique_per_loop_instance() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )

    first = ProjectProcedureWorkerLoop(operations)
    second = ProjectProcedureWorkerLoop(operations)

    assert first.worker_id.startswith("project-procedure-")
    assert second.worker_id.startswith("project-procedure-")
    assert first.worker_id != second.worker_id


def test_control_failures_back_off_exponentially() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    operations.due_error = httpx2.ReadError("daemon unavailable")
    loop = ProjectProcedureWorkerLoop(
        operations,
        backoff_initial_seconds=0.001,
        backoff_max_seconds=0.004,
    )
    stop = Event()
    delays: list[float] = []

    def observe_retry(_error: Exception, delay: float) -> None:
        delays.append(delay)
        if len(delays) == 4:
            stop.set()

    loop.run_forever(stop, poll_seconds=60, on_retry=observe_retry)

    assert delays == [0.001, 0.002, 0.004, 0.004]


@pytest.mark.parametrize(
    "cause",
    [
        httpx2.ReadError("publication lookup unavailable"),
        CalibrationPublicationDriftError("publication receipt drifted"),
    ],
)
def test_unknown_calibration_publication_outcome_uses_resident_backoff(
    cause: Exception,
) -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    unknown = CalibrationPublicationOutcomeUnknown(
        cast(
            "CalibrationCohortPublicationPlan",
            cast("object", SimpleNamespace(operation_id="publication-unknown")),
        ),
        cause=cause,
    )
    finalizer = _FakeCalibrationFinalizer(
        operations.calls,
        _publication_result(),
        error=unknown,
    )
    loop = ProjectProcedureWorkerLoop(
        operations,
        calibration_finalizer=finalizer,
        backoff_initial_seconds=0.001,
    )
    stop = Event()
    retries: list[tuple[Exception, float]] = []

    def observe_retry(error: Exception, delay: float) -> None:
        retries.append((error, delay))
        stop.set()

    loop.run_forever(stop, poll_seconds=60, on_retry=observe_retry)

    assert retries == [(unknown, 0.001)]


@pytest.mark.parametrize(
    "status",
    [503, 500, 429],
)
def test_transient_control_statuses_back_off(status: int) -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    operations.due_error = (
        _unavailable("daemon unavailable")
        if status == 503
        else _http_status(status, "daemon unavailable")
    )
    loop = ProjectProcedureWorkerLoop(
        operations,
        backoff_initial_seconds=0.001,
    )
    stop = Event()
    delays: list[float] = []

    def observe_retry(_error: Exception, delay: float) -> None:
        delays.append(delay)
        stop.set()

    loop.run_forever(stop, poll_seconds=60, on_retry=observe_retry)

    assert delays == [0.001]


def test_deterministic_query_error_does_not_enter_retry_loop() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    operations.due_error = _not_found("due route missing")
    retries: list[float] = []

    with pytest.raises(DaemonNotFoundError, match="due route missing"):
        ProjectProcedureWorkerLoop(operations).run_forever(
            Event(),
            poll_seconds=60,
            on_retry=lambda _error, delay: retries.append(delay),
        )

    assert retries == []


def test_poll_wait_is_interruptible_by_stop_event() -> None:
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(),
    )
    loop = ProjectProcedureWorkerLoop(operations)
    stop = Event()
    thread = Thread(
        target=lambda: loop.run_forever(stop, poll_seconds=60),
        daemon=True,
    )

    thread.start()
    assert operations.cycle_called.wait(1)
    stop.set()
    thread.join(1)

    assert not thread.is_alive()


def test_stop_event_yields_after_active_procedure_before_next_dispatch() -> None:
    stop = Event()
    operations = _FakeWorkerOperations(
        ProcedureScheduleDuePage(),
        ProcedureRunnablePage(items=(_run("run-1"), _run("run-2"))),
    )
    operations.stop_after_resume = stop
    loop = ProjectProcedureWorkerLoop(operations, worker_id="worker-stopping")

    result = loop.cycle(stop)

    assert result.dispatched_procedures == 1
    assert result.has_more is True
    assert operations.calls == [
        ("due", 50, None, None),
        ("runnable", 50),
        ("resume_snapshot", "run-1", "worker-stopping"),
    ]
    [should_yield] = operations.yield_callbacks
    assert should_yield is not None and should_yield()


def test_lab_procedure_operations_expose_exact_schedule_and_capability_api() -> None:
    client = _ScheduleClient()
    operations = LabProcedureOperations(
        client=cast("DaemonClient", cast("object", client)),
        runner=cast("_DaemonRunner", object()),
        config=cast("LabConfigOperations", object()),
        session=cast("ProcedureLabSession", object()),
        registry=ProcedureRegistry((SCHEDULED,)),
        schedule_registry=ProcedureScheduleRegistry(),
        worker_id="worker-test",
    )
    intent = ScheduledIntent(value=7)

    created = operations.create_schedule(
        SCHEDULED,
        intent,
        schedule_id="scheduled-exact",
        due_at=_DUE_AT,
    )
    assert created.schedule_id == "scheduled-exact"
    assert client.create_commands[0].definition == SCHEDULED.ref
    assert client.create_commands[0].intent == {"value": 7}

    assert operations.get_schedule("scheduled-exact").schedule_id == "scheduled-exact"
    assert operations.list_schedules(limit=12, before=9, state="pending").items
    assert client.list_queries == [
        ProcedureScheduleListQuery(limit=12, cursor=9, state="pending")
    ]
    assert operations.list_due_schedules(
        limit=4,
        cursor=3,
        through_sequence=10,
    ).items
    assert client.due_queries == [
        ProcedureScheduleDueQuery(limit=4, cursor=3, through_sequence=10)
    ]

    cancelled = operations.cancel_schedule(
        "scheduled-exact",
        expected_revision=1,
        actor="operator",
        reason="maintenance",
    )
    assert cancelled.state == "cancelled"
    assert client.cancel_commands == [
        ProcedureScheduleCancelCommand(
            schedule_id="scheduled-exact",
            expected_schedule_revision=1,
            actor="operator",
            reason="maintenance",
        )
    ]

    materialized = operations.materialize_schedule(
        "scheduled-exact",
        expected_revision=1,
    )
    assert materialized.state == "materialized"
    assert client.materialize_commands == [
        ProcedureScheduleMaterializeCommand(
            schedule_id="scheduled-exact",
            expected_schedule_revision=1,
        )
    ]

    operations.list_runnable(limit=8)
    [query] = client.runnable_queries
    assert query.definitions == (SCHEDULED.ref,)
    assert query.limit == 8


def test_lab_procedure_operations_resume_runnable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[ProcedureRun, str]] = []

    class SnapshotWorker:
        def resume_snapshot(
            self,
            run: ProcedureRun,
            *,
            worker_id: str,
            should_yield: Callable[[], bool] | None = None,
        ) -> ProcedureRun:
            assert should_yield is None
            calls.append((run, worker_id))
            return run

    snapshot_worker = SnapshotWorker()

    def worker(_operations: LabProcedureOperations) -> SnapshotWorker:
        return snapshot_worker

    monkeypatch.setattr(LabProcedureOperations, "_worker", worker)
    operations = LabProcedureOperations(
        client=cast("DaemonClient", object()),
        runner=cast("_DaemonRunner", object()),
        config=cast("LabConfigOperations", object()),
        session=cast("ProcedureLabSession", object()),
        registry=ProcedureRegistry((SCHEDULED,)),
        schedule_registry=ProcedureScheduleRegistry(),
        worker_id="worker-snapshot",
    )
    run = _run("run-snapshot")

    handle = operations.resume_snapshot(run)

    assert handle.id == run.procedure_run_id
    assert calls == [(run, "worker-snapshot")]


def _schedule(
    schedule_id: str,
    *,
    definition: ProcedureDefinitionRef = SCHEDULED.ref,
    intent: ProcedureIntent | None = None,
    due_at: datetime = _DUE_AT,
    state: ProcedureScheduleState = "pending",
    actor: str = "operator",
    reason: str = "cancelled",
) -> ProcedureSchedule:
    selected_intent: ProcedureIntent = {"value": 1} if intent is None else intent
    intent_hash = procedure_intent_hash(definition, selected_intent)
    updated_at = _CREATED_AT if state == "pending" else _TERMINAL_AT
    materialization = None
    cancellation = None
    if state == "materialized":
        materialization = ProcedureScheduleMaterialization(
            procedure_run_id=f"run-for-{schedule_id}",
            request_key=procedure_schedule_request_key(
                schedule_id,
                due_at,
                definition,
                intent_hash,
            ),
            materialized_at=_TERMINAL_AT,
        )
    elif state == "cancelled":
        cancellation = ProcedureScheduleCancellation(
            actor=actor,
            reason=reason,
            cancelled_at=_TERMINAL_AT,
        )
    return ProcedureSchedule(
        schedule_id=schedule_id,
        definition=definition,
        intent=selected_intent,
        intent_hash=intent_hash,
        due_at=due_at,
        revision=1 if state == "pending" else 2,
        state=state,
        created_at=_CREATED_AT,
        updated_at=updated_at,
        materialization=materialization,
        cancellation=cancellation,
    )


def _run(procedure_run_id: str) -> ProcedureRun:
    intent = {"value": 1}
    return ProcedureRun(
        procedure_run_id=procedure_run_id,
        request_key=f"request-{procedure_run_id}",
        definition=SCHEDULED.ref,
        intent=intent,
        intent_hash=procedure_intent_hash(SCHEDULED.ref, intent),
        revision=1,
        state="ready",
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _conflict(detail: str) -> DaemonConflictError:
    response = _response(409)
    return DaemonConflictError(detail, response=response)


def _not_found(detail: str) -> DaemonNotFoundError:
    return DaemonNotFoundError(detail, response=_response(404))


def _unavailable(detail: str) -> DaemonUnavailableError:
    return DaemonUnavailableError(detail, response=_response(503))


def _http_status(status: int, detail: str) -> httpx2.HTTPStatusError:
    response = _response(status)
    return httpx2.HTTPStatusError(
        detail,
        request=response.request,
        response=response,
    )


def _response(status: int) -> httpx2.Response:
    return httpx2.Response(
        status,
        request=httpx2.Request("POST", "http://daemon.local/procedures"),
    )


def _lease(procedure_run_id: str) -> ProcedureWorkerLease:
    return ProcedureWorkerLease(
        procedure_run_id=procedure_run_id,
        worker_id="worker-test",
        lease_token=f"lease-{procedure_run_id}",
        issued_at=_CREATED_AT,
        renewed_at=_CREATED_AT,
        expires_at=_CREATED_AT + timedelta(minutes=1),
        heartbeat_interval_seconds=1,
    )
