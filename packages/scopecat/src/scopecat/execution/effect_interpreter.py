"""Synchronous coverage orchestration for a provisioned ``RunProgram``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import cast

import scopecat.execution.effect_result as effect_result
from scopecat.execution.effects.compute import ComputeEffectExecutor, PointEffectState
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.effects.hardware import HardwareEffectExecutor
from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    InvokeOperation,
)
from scopecat.execution.points import AdmittedPointLedger
from scopecat.execution.ports.instruments import RunInstrumentHost
from scopecat.execution.program import (
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
)
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.value_data import CellValue
from scopecat.measurements.points import RunPoint
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.journal import ExecutionJournal, ExecutionJournalError
from scopecat.sdk.payloads import EMPTY_PAYLOAD_CODECS, PayloadCodecRegistry


class _CapturedDomainEffectFailure(Exception):
    """Stop the operation loop after retaining a structured domain failure."""


class _CapturedCoverageFailure(Exception):
    """Stop after retaining a failure from the coverage consumer."""


class _CancellationRequested(Exception):
    """Stop at an interpreter checkpoint after recording the durable reason."""


def _never_cancel() -> bool:
    return False


class RunEffectInterpreter:
    """Execute provisioned host operations in exact program order.

    The caller must create the durable run skeleton before invoking ``run``.
    Terminal certainty and run outcome are derived by the outer run boundary
    from the facts returned here.
    """

    def __init__(
        self,
        *,
        run_id: str,
        coordinate_ids: Sequence[str],
        instruments: RunInstrumentHost,
        journal: ExecutionJournal,
        coverage_observer: effect_result.CoverageMeasurementObserver | None = None,
        recorded_value_ids: Sequence[ValueId] = (),
        payload_codecs: PayloadCodecRegistry = EMPTY_PAYLOAD_CODECS,
        cancellation_requested: Callable[[], bool] = _never_cancel,
    ) -> None:
        self.run_id = run_id
        self.point_ledger = AdmittedPointLedger(
            coordinate_ids=tuple(coordinate_ids),
        )
        self.logical_points: dict[int, LogicalPointId] = {}
        self.run_points: dict[int, RunPoint] = {}
        self.observed_state = list(instruments.observed_state)
        self.prepared_state = list(instruments.prepared_state)
        self.final_state: list[InstrumentStateSnapshot] = []
        self.domain_failure: tuple[RunDomainJob, BaseException] | None = None
        self.coverage_failure: BaseException | None = None
        self.cancelled = False
        self._point_states: dict[int, PointEffectState] = {}
        self._active_point_indices: set[int] = set()
        self._terminal_point_indices: set[int] = set()

        self._journal = JournaledEffectBoundary(run_id=run_id, journal=journal)
        self._compute = ComputeEffectExecutor(
            journal=self._journal,
            payload_codecs=payload_codecs,
        )
        self._hardware = HardwareEffectExecutor(
            instruments=instruments,
            problems=self._journal,
        )
        self._coverage_observer = coverage_observer
        self._recorded_value_ids = tuple(recorded_value_ids)
        self._instruments = instruments
        self._cancellation_requested = cancellation_requested

    def run(
        self,
        coverage: Iterable[RunCoveredOperation],
        *,
        points: Sequence[RunPoint],
        success_state: Sequence[ApplyStateOperation] = (),
    ) -> effect_result.RunEffectResult:
        """Interpret the residual effect sequence exactly in program order."""

        try:
            self._check_cancellation()
            if not self._journal.problems:
                admitted = self.point_ledger.admit(points)
                self.run_points.update((point.ordinal, point) for point in admitted)
                self.logical_points.update(
                    (point.ordinal, point.logical_id) for point in admitted
                )
                self._execute_coverage_operations(coverage)
            if (
                not bool(self._journal.problems)
                and self.domain_failure is None
                and self._terminal_point_indices != set(self.logical_points)
            ):
                raise AssertionError("run ended without completing every logical point")
            if (
                not bool(self._journal.problems)
                and not self._journal.indeterminate
                and self._journal.interruption is None
                and self.domain_failure is None
                and self.coverage_failure is None
            ):
                self._check_cancellation()
                if self._hardware.execute_success_state(success_state):
                    self._check_cancellation()
        except ExecutionJournalError as error:
            self._journal.problems.append(
                self._journal.problem(
                    "execution_journal_commit_failed",
                    str(error),
                    phase=ProblemPhase.PERSISTENCE,
                )
            )
        except _CapturedDomainEffectFailure:
            pass
        except _CapturedCoverageFailure:
            pass
        except _CancellationRequested:
            pass
        except Exception as error:
            self._journal.problems.append(
                self._journal.problem_from_exception(
                    "run_effect_interpretation_failed",
                    "run effect interpretation failed",
                    error,
                )
            )
        except BaseException as error:
            self._journal.record_interruption(error)
        finally:
            if self._active_point_indices:
                self._complete_coverage(
                    tuple(sorted(self._active_point_indices)),
                )
            try:
                finished = self._instruments.finish(
                    operation_id="hardware.finish",
                    failed=(
                        bool(self._journal.problems)
                        or self._journal.indeterminate
                        or self._journal.interruption is not None
                        or self.domain_failure is not None
                        or self.coverage_failure is not None
                    ),
                )
                self.final_state = list(finished.final_state)
                self._journal.problems.extend(finished.problems)
                self._journal.indeterminate = (
                    self._journal.indeterminate or finished.indeterminate
                )
            except Exception as error:
                self._journal.indeterminate = True
                self._journal.problems.append(
                    self._journal.problem_from_exception(
                        "hardware_finalization_unknown",
                        "daemon hardware finalization outcome is unknown",
                        error,
                        operation_id="hardware.finish",
                    )
                )
        return self._result()

    def _execute_coverage_operations(
        self,
        operations: Iterable[RunCoveredOperation],
    ) -> None:
        hardware: list[RunCoverageEffect] = []
        for operation in operations:
            self._check_cancellation()
            if isinstance(operation, RunCoverageEffect) and isinstance(
                operation.operation,
                ApplyStateOperation | InvokeOperation | CollectOperation,
            ):
                self._point_state(operation.point_index)
                hardware.append(operation)
                continue
            if hardware:
                self._check_cancellation()
                if not self._hardware.execute(
                    hardware,
                    frame_for=self._point_state,
                ):
                    return
                hardware.clear()
                self._check_cancellation()
            if isinstance(operation, RunCoverageCheckpoint):
                self._commit_coverage_checkpoint(operation)
                continue
            self._execute_covered_operation(operation)
            if bool(self._journal.problems):
                return
            self._check_cancellation()
        if hardware:
            self._check_cancellation()
            if not self._hardware.execute(
                hardware,
                frame_for=self._point_state,
            ):
                return
            self._check_cancellation()
        remaining = tuple(
            point_index
            for point_index in self.logical_points
            if point_index not in self._terminal_point_indices
        )
        if remaining:
            self._commit_coverage(remaining)
            self._check_cancellation()

    def _commit_coverage_checkpoint(
        self,
        checkpoint: RunCoverageCheckpoint,
    ) -> None:
        if checkpoint.point_index not in self.logical_points:
            raise AssertionError("coverage checkpoint references an unknown point")
        self._commit_coverage((checkpoint.point_index,))

    def _commit_coverage(
        self,
        point_indices: tuple[int, ...],
    ) -> None:
        value_candidates = tuple(
            ValueRecordCandidate(
                logical_point_id=self.logical_points[point_index],
                value_id=value_id,
                value=cast("CellValue", state.compute_results[value_id]),
            )
            for point_index in point_indices
            if (state := self._point_states.get(point_index)) is not None
            for value_id in self._recorded_value_ids
            if value_id in state.compute_results
        )
        self._complete_coverage(point_indices)
        try:
            points = tuple(
                self.run_points[point_index] for point_index in point_indices
            )
            if self._coverage_observer is not None:
                selected = frozenset(point_indices)
                candidates = tuple(
                    candidate
                    for candidate in self._hardware.values
                    if candidate.logical_point_id.logical_ordinal in selected
                )
                self._coverage_observer(points, candidates, value_candidates)
                self._hardware.values[:] = (
                    candidate
                    for candidate in self._hardware.values
                    if candidate.logical_point_id.logical_ordinal not in selected
                )
        except BaseException as error:
            self.coverage_failure = error
            raise _CapturedCoverageFailure from error

    def _execute_covered_operation(self, operation: RunCoveredOperation) -> None:
        match operation:
            case RunCoverageCheckpoint():
                raise AssertionError("coverage checkpoint bypassed block sequencing")
            case RunDomainJob():
                self._execute_domain_job(operation)
            case RunCoverageEffect():
                self._execute_coverage_effect(operation)

    def _execute_coverage_effect(self, covered: RunCoverageEffect) -> None:
        if not isinstance(covered.operation, ComputeOperation):
            raise AssertionError("hardware effect bypassed batch execution")
        self._compute.execute(
            self._point_state(covered.point_index),
            (covered.operation,),
        )

    def _execute_domain_job(self, job: RunDomainJob) -> None:
        for point_index in job.point_ordinals:
            if point_index in self._terminal_point_indices:
                raise AssertionError("domain job follows point completion")
            if point_index not in self.logical_points:
                raise AssertionError("domain job references an unknown point")
            self._active_point_indices.add(point_index)
        try:
            values = execute_domain_job_values(
                job.execution,
                logical_compute_node_id=job.id,
                run_id=self.run_id,
                journal=self._journal.execution_journal,
            )
        except BaseException as error:
            self.domain_failure = (job, error)
            pending = tuple(sorted(self._active_point_indices))
            if pending:
                self._complete_coverage(pending)
            raise _CapturedDomainEffectFailure(job.id) from error
        self._hardware.values.extend(values)

    def _point_state(self, point_index: int) -> PointEffectState:
        if point_index in self._terminal_point_indices:
            raise AssertionError("point effect follows point completion")
        state = self._point_states.get(point_index)
        if state is not None:
            return state
        try:
            logical_id = self.logical_points[point_index]
        except KeyError as error:
            raise AssertionError("point effect references an unknown point") from error
        state = PointEffectState(
            point_index=point_index,
            logical_id=logical_id,
        )
        self._point_states[point_index] = state
        self._active_point_indices.add(point_index)
        return state

    def _complete_coverage(
        self,
        point_indices: tuple[int, ...],
    ) -> None:
        if not point_indices or len(point_indices) != len(set(point_indices)):
            raise AssertionError("point coverage must be non-empty and unique")
        if any(
            point_index in self._terminal_point_indices for point_index in point_indices
        ):
            raise AssertionError("point coverage overlaps completed points")
        if any(point_index not in self.logical_points for point_index in point_indices):
            raise AssertionError("point coverage references an unknown point")
        for point_index in point_indices:
            self._point_states.pop(point_index, None)
            self._active_point_indices.discard(point_index)
        self._terminal_point_indices.update(point_indices)

    def _check_cancellation(self) -> None:
        if self.cancelled or not self._cancellation_requested():
            return
        self.cancelled = True
        self._journal.problems.append(
            self._journal.problem(
                "run_cancellation_requested",
                "run stopped at a safe checkpoint after cancellation was requested",
            )
        )
        raise _CancellationRequested

    def _result(self) -> effect_result.RunEffectResult:
        return effect_result.RunEffectResult(
            problems=tuple(self._journal.problems),
            observed_state=tuple(self.observed_state),
            prepared_state=tuple(self.prepared_state),
            final_state=tuple(self.final_state),
            admitted_points=self.point_ledger.points,
            indeterminate=self._journal.indeterminate,
            cancelled=self.cancelled,
            domain_failure=self.domain_failure,
            coverage_failure=self.coverage_failure,
            interruption=self._journal.interruption,
        )


__all__ = ["RunEffectInterpreter"]
