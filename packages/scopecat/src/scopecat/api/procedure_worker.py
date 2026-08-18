"""Project-owned polling loop for scheduled and runnable procedures."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Literal, Protocol, cast
from uuid import uuid4

import httpx2

from scopecat.api.calibration_planner import CalibrationEvaluatorCycleResult
from scopecat.api.procedure_planner import ProcedurePlannerCycleResult
from scopecat.api.procedures import ProcedureHandle
from scopecat.automation import (
    ProcedureControlError,
    ProcedureLeaseLostError,
    ProcedureRun,
    ProcedureRunnablePage,
    ProcedureSchedule,
    ProcedureScheduleDuePage,
)
from scopecat.daemon.client import DaemonClientError, DaemonConflictError

_DEFAULT_BATCH_LIMIT = 50
_DEFAULT_BACKOFF_INITIAL_SECONDS = 0.25
_DEFAULT_BACKOFF_MAX_SECONDS = 10.0
_TRANSIENT_CLIENT_STATUSES = frozenset({408, 425, 429})

_LOGGER = logging.getLogger(__name__)


class ProcedureWorkerOperations(Protocol):
    """High-level operations consumed by the project worker loop."""

    def list_due_schedules(
        self,
        *,
        limit: int = 50,
        cursor: int | None = None,
        through_sequence: int | None = None,
    ) -> ProcedureScheduleDuePage: ...

    def get_schedule(self, schedule_id: str) -> ProcedureSchedule: ...

    def materialize_schedule(
        self,
        schedule_id: str,
        *,
        expected_revision: int,
    ) -> ProcedureSchedule: ...

    def list_runnable(self, *, limit: int = 50) -> ProcedureRunnablePage: ...

    def resume_snapshot(
        self,
        run: ProcedureRun,
        *,
        worker_id: str | None = None,
        should_yield: Callable[[], bool] | None = None,
    ) -> ProcedureHandle: ...


class ProcedureIntervalPlanner(Protocol):
    """Project-side latest-only planner invoked before due discovery."""

    def cycle(self, stop: Event | None = None) -> ProcedurePlannerCycleResult: ...


class CalibrationEvaluator(Protocol):
    """Project-side freshness evaluator invoked before due discovery."""

    def cycle(self, stop: Event | None = None) -> CalibrationEvaluatorCycleResult: ...


@dataclass(frozen=True, slots=True)
class ProcedureWorkerCycleResult:
    """Bounded work and benign races observed during one worker cycle."""

    eligible_interval_occurrences: int
    created_interval_schedules: int
    existing_interval_schedules: int
    reconciled_interval_schedules: int
    interval_schedule_drifts: int
    planner_failures: int
    selected_calibration_targets: int
    fresh_calibrations: int
    blocked_calibrations: int
    suppressed_active_calibrations: int
    suppressed_failed_calibrations: int
    suppressed_attention_calibrations: int
    ready_calibrations: int
    admitted_calibrations: int
    created_calibration_cohorts: int
    reconciled_calibration_cohorts: int
    calibration_admission_conflicts: int
    calibration_cohort_drifts: int
    calibration_failures: int
    due_schedules: int
    materialized_schedules: int
    schedule_conflicts: int
    schedule_failures: int
    runnable_procedures: int
    dispatched_procedures: int
    procedure_failures: int
    procedure_conflicts: int
    lease_conflicts: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class _ScheduleCycleResult:
    discovered: int
    materialized: int
    conflicts: int
    failures: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class _ProcedureCycleResult:
    discovered: int
    dispatched: int
    failures: int
    conflicts: int
    lease_conflicts: int
    has_more: bool


type _ScheduleOutcome = Literal["materialized", "conflict", "failure"]


class ProjectProcedureWorkerLoop:
    """Materialize due schedules and execute compatible project procedures."""

    __slots__ = (
        "_backoff_initial_seconds",
        "_backoff_max_seconds",
        "_calibration_evaluator",
        "_due_traversal",
        "_operations",
        "_planner",
        "_runnable_limit",
        "_schedule_limit",
        "_worker_id",
    )

    def __init__(
        self,
        operations: ProcedureWorkerOperations,
        *,
        planner: ProcedureIntervalPlanner | None = None,
        calibration_evaluator: CalibrationEvaluator | None = None,
        worker_id: str | None = None,
        schedule_limit: int = _DEFAULT_BATCH_LIMIT,
        runnable_limit: int = _DEFAULT_BATCH_LIMIT,
        backoff_initial_seconds: float = _DEFAULT_BACKOFF_INITIAL_SECONDS,
        backoff_max_seconds: float = _DEFAULT_BACKOFF_MAX_SECONDS,
    ) -> None:
        if not 1 <= schedule_limit <= 200:
            raise ValueError("procedure schedule batch limit must be between 1 and 200")
        if not 1 <= runnable_limit <= 200:
            raise ValueError("runnable procedure batch limit must be between 1 and 200")
        if backoff_initial_seconds <= 0:
            raise ValueError("procedure worker initial backoff must be positive")
        if backoff_max_seconds < backoff_initial_seconds:
            raise ValueError(
                "procedure worker maximum backoff must not be below its initial backoff"
            )
        selected_worker_id = worker_id or f"project-procedure-{uuid4().hex}"
        if not selected_worker_id.strip():
            raise ValueError("procedure worker id must be non-empty")

        self._operations = operations
        self._planner = planner
        self._calibration_evaluator = calibration_evaluator
        self._worker_id = selected_worker_id
        self._schedule_limit = schedule_limit
        self._runnable_limit = runnable_limit
        self._backoff_initial_seconds = backoff_initial_seconds
        self._backoff_max_seconds = backoff_max_seconds
        self._due_traversal: tuple[int, int] | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def cycle(self, stop: Event | None = None) -> ProcedureWorkerCycleResult:
        """Run one bounded plan-materialize-dispatch cycle."""

        planning = (
            _empty_planner_cycle()
            if self._planner is None
            else self._planner.cycle(stop)
        )
        if stop is not None and stop.is_set():
            return _worker_cycle_result(
                planning,
                _empty_calibration_cycle(),
                _ScheduleCycleResult(0, 0, 0, 0, False),
                _ProcedureCycleResult(0, 0, 0, 0, 0, False),
            )
        calibrations = (
            _empty_calibration_cycle()
            if self._calibration_evaluator is None
            else self._calibration_evaluator.cycle(stop)
        )
        if stop is not None and stop.is_set():
            return _worker_cycle_result(
                planning,
                calibrations,
                _ScheduleCycleResult(0, 0, 0, 0, False),
                _ProcedureCycleResult(0, 0, 0, 0, 0, False),
            )
        schedules = self._materialize_due(stop)
        if stop is not None and stop.is_set():
            return _worker_cycle_result(
                planning,
                calibrations,
                schedules,
                _ProcedureCycleResult(0, 0, 0, 0, 0, False),
            )

        procedures = self._dispatch_runnable(stop)
        return _worker_cycle_result(planning, calibrations, schedules, procedures)

    def _materialize_due(self, stop: Event | None) -> _ScheduleCycleResult:
        cursor, through_sequence = self._due_traversal or (None, None)
        page = self._operations.list_due_schedules(
            limit=self._schedule_limit,
            cursor=cursor,
            through_sequence=through_sequence,
        )
        outcomes: list[_ScheduleOutcome] = []
        for schedule in page.items:
            if stop is not None and stop.is_set():
                break
            outcomes.append(self._materialize_one(schedule))
        if stop is None or not stop.is_set():
            self._due_traversal = (
                None
                if page.next_cursor is None
                else (page.next_cursor, cast("int", page.through_sequence))
            )
        return _ScheduleCycleResult(
            discovered=len(page.items),
            materialized=outcomes.count("materialized"),
            conflicts=outcomes.count("conflict"),
            failures=outcomes.count("failure"),
            has_more=(page.next_cursor is not None or len(outcomes) < len(page.items)),
        )

    def _materialize_one(self, schedule: ProcedureSchedule) -> _ScheduleOutcome:
        try:
            self._operations.materialize_schedule(
                schedule.schedule_id,
                expected_revision=schedule.revision,
            )
        except DaemonConflictError:
            try:
                observed = self._operations.get_schedule(schedule.schedule_id)
            except Exception as error:
                if _is_deterministic_client_error(error):
                    return "failure"
                raise
            if observed.state != "pending" or observed.revision != schedule.revision:
                return "conflict"
            return "failure"
        except (DaemonClientError, httpx2.HTTPError) as error:
            if _is_deterministic_client_error(error):
                return "failure"
            raise
        return "materialized"

    def _dispatch_runnable(self, stop: Event | None) -> _ProcedureCycleResult:
        page = self._operations.list_runnable(limit=self._runnable_limit)
        dispatched = 0
        failures = 0
        conflicts = 0
        lease_conflicts = 0
        processed = 0
        for run in page.items:
            if stop is not None and stop.is_set():
                break
            processed += 1
            try:
                self._operations.resume_snapshot(
                    run,
                    worker_id=self._worker_id,
                    should_yield=(None if stop is None else stop.is_set),
                )
            except ProcedureControlError as error:
                if error.operation == "acquire_procedure_worker_lease":
                    if _error_status(error) == 409:
                        lease_conflicts += 1
                        continue
                    raise
                if _is_deterministic_client_error(error):
                    conflicts += 1
                    continue
                raise
            except ProcedureLeaseLostError as error:
                if _error_status(error) == 409:
                    lease_conflicts += 1
                    continue
                if _is_deterministic_client_error(error):
                    conflicts += 1
                    continue
                raise
            except Exception:
                failures += 1
                _LOGGER.exception(
                    "procedure %s failed after acquiring worker authority",
                    run.procedure_run_id,
                )
            else:
                dispatched += 1
        return _ProcedureCycleResult(
            discovered=len(page.items),
            dispatched=dispatched,
            failures=failures,
            conflicts=conflicts,
            lease_conflicts=lease_conflicts,
            has_more=(page.has_more or processed < len(page.items)),
        )

    def run_forever(
        self,
        stop: Event,
        *,
        poll_seconds: float = 1.0,
        on_cycle: Callable[[ProcedureWorkerCycleResult], None] | None = None,
        on_retry: Callable[[Exception, float], None] | None = None,
    ) -> None:
        """Poll until stopped, backing off retryable control-plane failures."""

        if poll_seconds <= 0:
            raise ValueError("procedure worker poll interval must be positive")
        backoff_seconds = self._backoff_initial_seconds
        while not stop.is_set():
            try:
                result = self.cycle(stop)
            except _worker_control_errors() as error:
                if not _is_retryable_control_error(error):
                    raise
                if on_retry is not None:
                    on_retry(error, backoff_seconds)
                if stop.wait(backoff_seconds):
                    return
                backoff_seconds = min(
                    backoff_seconds * 2,
                    self._backoff_max_seconds,
                )
                continue

            backoff_seconds = self._backoff_initial_seconds
            if on_cycle is not None:
                on_cycle(result)
            wait_seconds = 0.0 if result.has_more else poll_seconds
            if stop.wait(wait_seconds):
                return


def _is_deterministic_client_error(error: Exception) -> bool:
    status = _error_status(error)
    return (
        status is not None
        and 400 <= status < 500
        and status not in _TRANSIENT_CLIENT_STATUSES
    )


def _empty_planner_cycle() -> ProcedurePlannerCycleResult:
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


def _empty_calibration_cycle() -> CalibrationEvaluatorCycleResult:
    return CalibrationEvaluatorCycleResult(
        definitions=0,
        selected_targets=0,
        fresh_members=0,
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


def _worker_cycle_result(
    planning: ProcedurePlannerCycleResult,
    calibrations: CalibrationEvaluatorCycleResult,
    schedules: _ScheduleCycleResult,
    procedures: _ProcedureCycleResult,
) -> ProcedureWorkerCycleResult:
    return ProcedureWorkerCycleResult(
        eligible_interval_occurrences=planning.eligible_occurrences,
        created_interval_schedules=planning.created_schedules,
        existing_interval_schedules=planning.existing_schedules,
        reconciled_interval_schedules=planning.reconciled_schedules,
        interval_schedule_drifts=planning.drifted_schedules,
        planner_failures=planning.failures,
        selected_calibration_targets=calibrations.selected_targets,
        fresh_calibrations=calibrations.fresh_members,
        blocked_calibrations=calibrations.blocked_members,
        suppressed_active_calibrations=calibrations.suppressed_active_members,
        suppressed_failed_calibrations=calibrations.suppressed_failed_members,
        suppressed_attention_calibrations=(calibrations.suppressed_attention_members),
        ready_calibrations=calibrations.ready_members,
        admitted_calibrations=calibrations.admitted_members,
        created_calibration_cohorts=calibrations.created_cohorts,
        reconciled_calibration_cohorts=calibrations.reconciled_cohorts,
        calibration_admission_conflicts=calibrations.admission_conflicts,
        calibration_cohort_drifts=calibrations.cohort_drifts,
        calibration_failures=calibrations.failures,
        due_schedules=schedules.discovered,
        materialized_schedules=schedules.materialized,
        schedule_conflicts=schedules.conflicts,
        schedule_failures=schedules.failures,
        runnable_procedures=procedures.discovered,
        dispatched_procedures=procedures.dispatched,
        procedure_failures=procedures.failures,
        procedure_conflicts=procedures.conflicts,
        lease_conflicts=procedures.lease_conflicts,
        has_more=(
            planning.has_more
            or calibrations.has_more
            or schedules.has_more
            or procedures.has_more
        ),
    )


def _is_retryable_control_error(error: Exception) -> bool:
    cause = _control_cause(error)
    if isinstance(cause, httpx2.TransportError):
        return True
    status = _error_status(cause)
    return status is not None and (
        status == 503 or status >= 500 or status in _TRANSIENT_CLIENT_STATUSES
    )


def _control_cause(error: Exception) -> Exception:
    selected = error
    while isinstance(selected, (ProcedureControlError, ProcedureLeaseLostError)):
        selected = selected.cause
    return selected


def _error_status(error: Exception) -> int | None:
    selected = _control_cause(error)
    if isinstance(selected, (DaemonClientError, httpx2.HTTPStatusError)):
        return selected.response.status_code
    return None


def _worker_control_errors() -> tuple[type[Exception], ...]:
    return (
        ProcedureControlError,
        ProcedureLeaseLostError,
        DaemonClientError,
        httpx2.HTTPError,
    )


__all__ = [
    "CalibrationEvaluator",
    "ProcedureIntervalPlanner",
    "ProcedureWorkerCycleResult",
    "ProcedureWorkerOperations",
    "ProjectProcedureWorkerLoop",
]
