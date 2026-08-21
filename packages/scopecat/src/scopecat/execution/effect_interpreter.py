"""Synchronous coverage orchestration for a provisioned ``RunProgram``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import scopecat.execution.effect_result as effect_result
from scopecat.execution.effects.boundary import EffectBoundary
from scopecat.execution.effects.compute import ComputeEffectExecutor, PointEffectState
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.effects.hardware import HardwareEffectExecutor
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    InvokeOperation,
)
from scopecat.execution.program import (
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
)
from scopecat.execution.services import RunDomainJobCheckpointWriter
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.domain.evidence import DomainExecutionAttemptEvidence
from scopecat.sdk.domain.runtime import (
    DomainExecutionCancellationRequested,
    DomainExecutionId,
    DomainExecutionReceipt,
    DomainJobCheckpoint,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunInstrumentHost,
)
from scopecat.sdk.payloads import EMPTY_PAYLOAD_CODECS, PayloadCodecRegistry


class _CapturedDomainEffectFailure(Exception):
    """Stop the operation loop after retaining a structured domain failure."""


class _CapturedCoverageFailure(Exception):
    """Stop after retaining a failure from the coverage consumer."""


class _CancellationRequested(Exception):
    """Stop at an interpreter checkpoint after recording the durable reason."""


class _CancellationAwareDomainInstruments:
    """Fence each nested domain batch with the run cancellation signal."""

    def __init__(
        self,
        instruments: RunInstrumentHost,
        cancellation_requested: Callable[[], bool],
    ) -> None:
        self._instruments = instruments
        self._cancellation_requested = cancellation_requested

    def execute(self, batch: RunHardwareBatch) -> RunHardwareBatchReceipt:
        if self._cancellation_requested():
            raise DomainExecutionCancellationRequested
        return self._instruments.execute(batch)


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
        coverage_observer: effect_result.CoverageMeasurementObserver | None = None,
        recorded_value_ids: Sequence[ValueId] = (),
        payload_codecs: PayloadCodecRegistry = EMPTY_PAYLOAD_CODECS,
        cancellation_requested: Callable[[], bool] = _never_cancel,
        domain_job_checkpoints: RunDomainJobCheckpointWriter | None = None,
    ) -> None:
        self.run_id = run_id
        self.coordinate_ids = frozenset(coordinate_ids)
        self.run_points: Sequence[AcceptedRunPoint] = ()
        self.observed_state = list(instruments.observed_state)
        self.baseline_state = list(instruments.baseline_state)
        self.final_state: list[InstrumentStateSnapshot] = []
        self.domain_execution_attempts: list[DomainExecutionAttemptEvidence] = []
        self.domain_failure: tuple[RunDomainJob, BaseException] | None = None
        self.coverage_failure: BaseException | None = None
        self.cancelled = False
        self._point_states: dict[int, PointEffectState] = {}
        self._active_point_indices: set[int] = set()
        self._terminal_point_indices: set[int] = set()

        self._boundary = EffectBoundary(run_id=run_id)
        self._compute = ComputeEffectExecutor(
            boundary=self._boundary,
            payload_codecs=payload_codecs,
        )
        self._hardware = HardwareEffectExecutor(
            instruments=instruments,
            problems=self._boundary,
        )
        self._coverage_observer = coverage_observer
        self._recorded_value_ids = tuple(recorded_value_ids)
        self._instruments = instruments
        self._cancellation_requested = cancellation_requested
        self._domain_job_checkpoints = domain_job_checkpoints
        self._domain_instruments = _CancellationAwareDomainInstruments(
            instruments,
            cancellation_requested,
        )

    def run(
        self,
        coverage: Iterable[RunCoveredOperation],
        *,
        points: Sequence[AcceptedRunPoint],
        success_state: Sequence[ApplyStateOperation] = (),
    ) -> effect_result.RunEffectResult:
        """Interpret the residual effect sequence exactly in program order."""

        try:
            self._check_cancellation()
            if not self._boundary.problems:
                self.run_points = points
                self._execute_coverage_operations(coverage)
            if (
                not bool(self._boundary.problems)
                and self.domain_failure is None
                and len(self._terminal_point_indices) != len(self.run_points)
            ):
                raise AssertionError("run ended without completing every logical point")
            if (
                not bool(self._boundary.problems)
                and not self._boundary.indeterminate
                and self._boundary.interruption is None
                and self.domain_failure is None
                and self.coverage_failure is None
            ):
                self._check_cancellation()
                if self._hardware.execute_success_state(success_state):
                    self._check_cancellation()
        except CheckFailed as error:
            self._boundary.problems.extend(error.problems)
        except _CapturedDomainEffectFailure:
            pass
        except _CapturedCoverageFailure:
            pass
        except _CancellationRequested:
            pass
        except Exception as error:
            self._boundary.problems.append(
                self._boundary.problem_from_exception(
                    "run_effect_interpretation_failed",
                    "run effect interpretation failed",
                    error,
                )
            )
        except BaseException as error:
            self._boundary.record_interruption(error)
        finally:
            if self._active_point_indices:
                self._complete_coverage(
                    tuple(sorted(self._active_point_indices)),
                )
            try:
                finished = self._instruments.finish(
                    operation_id="hardware.finish",
                    failed=(
                        bool(self._boundary.problems)
                        or self._boundary.indeterminate
                        or self._boundary.interruption is not None
                        or self.domain_failure is not None
                        or self.coverage_failure is not None
                    ),
                )
                self.final_state = list(finished.final_state)
                self._boundary.problems.extend(finished.problems)
                self._boundary.indeterminate = (
                    self._boundary.indeterminate or finished.indeterminate
                )
            except Exception as error:
                self._boundary.indeterminate = True
                self._boundary.problems.append(
                    self._boundary.problem_from_exception(
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
            if bool(self._boundary.problems):
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
            for point_index in range(len(self.run_points))
            if point_index not in self._terminal_point_indices
        )
        if remaining:
            self._commit_coverage(remaining)
            self._check_cancellation()

    def _commit_coverage_checkpoint(
        self,
        checkpoint: RunCoverageCheckpoint,
    ) -> None:
        if not self._known_point(checkpoint.point_index):
            raise AssertionError("coverage checkpoint references an unknown point")
        self._commit_coverage((checkpoint.point_index,))

    def _commit_coverage(
        self,
        point_indices: tuple[int, ...],
    ) -> None:
        value_candidates = tuple(
            ValueRecordCandidate(
                logical_point_id=self._point(point_index).logical_id,
                value_id=value_id,
                value=state.compute_results[value_id],
            )
            for point_index in point_indices
            if (state := self._point_states.get(point_index)) is not None
            for value_id in self._recorded_value_ids
            if value_id in state.compute_results
        )
        self._complete_coverage(point_indices)
        try:
            points = tuple(self._point(point_index) for point_index in point_indices)
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
            if not self._known_point(point_index):
                raise AssertionError("domain job references an unknown point")
            self._active_point_indices.add(point_index)
        try:
            execute_domain_job_values(
                job.execution,
                logical_compute_node_id=job.id,
                run_id=self.run_id,
                instruments=self._domain_instruments,
                accept=self._hardware.values.append,
                observe_attempt=lambda execution_id, checkpoints, receipt: (
                    self._record_domain_attempt(
                        job,
                        execution_id,
                        checkpoints,
                        receipt,
                    )
                ),
                commit_checkpoint=lambda _execution_id, checkpoint: (
                    self._commit_domain_job_checkpoint(
                        job,
                        checkpoint,
                    )
                ),
            )
        except DomainExecutionCancellationRequested:
            self._check_cancellation()
            raise AssertionError(
                "domain cancellation marker requires a live request"
            ) from None
        except BaseException as error:
            self.domain_failure = (job, error)
            pending = tuple(sorted(self._active_point_indices))
            if pending:
                self._complete_coverage(pending)
            raise _CapturedDomainEffectFailure(job.id) from error

    def _commit_domain_job_checkpoint(
        self,
        job: RunDomainJob,
        checkpoint: DomainJobCheckpoint,
    ) -> None:
        writer = self._domain_job_checkpoints
        if writer is not None:
            writer.commit(
                logical_compute_node_id=job.id,
                point_ordinals=job.point_ordinals,
                checkpoint=checkpoint,
            )
        if self._cancellation_requested():
            raise DomainExecutionCancellationRequested

    def _record_domain_attempt(
        self,
        job: RunDomainJob,
        execution_id: DomainExecutionId,
        checkpoints: tuple[DomainJobCheckpoint, ...],
        receipt: DomainExecutionReceipt | None,
    ) -> None:
        self.domain_execution_attempts.append(
            DomainExecutionAttemptEvidence(
                logical_compute_node_id=job.id,
                point_ordinals=job.point_ordinals,
                execution_key=execution_id.execution_key,
                intent=job.execution.invocation.intent,
                checkpoints=checkpoints,
                receipt=receipt,
            )
        )

    def _point_state(self, point_index: int) -> PointEffectState:
        if point_index in self._terminal_point_indices:
            raise AssertionError("point effect follows point completion")
        state = self._point_states.get(point_index)
        if state is not None:
            return state
        logical_id = self._point(point_index).logical_id
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
        if any(not self._known_point(point_index) for point_index in point_indices):
            raise AssertionError("point coverage references an unknown point")
        for point_index in point_indices:
            self._point_states.pop(point_index, None)
            self._active_point_indices.discard(point_index)
        self._terminal_point_indices.update(point_indices)

    def _known_point(self, point_index: int) -> bool:
        return 0 <= point_index < len(self.run_points)

    def _point(self, point_index: int) -> AcceptedRunPoint:
        if not self._known_point(point_index):
            raise AssertionError("point effect references an unknown point")
        point = self.run_points[point_index]
        if point.ordinal != point_index:
            raise ValueError("run points must retain canonical contiguous ordinals")
        if frozenset(point.coordinates) != self.coordinate_ids:
            raise ValueError("run point coordinates do not match the run contract")
        return point

    def _check_cancellation(self) -> None:
        if self.cancelled or not self._cancellation_requested():
            return
        self.cancelled = True
        self._boundary.problems.append(
            self._boundary.problem(
                "run_cancellation_requested",
                "run stopped at a safe checkpoint after cancellation was requested",
            )
        )
        raise _CancellationRequested

    def _result(self) -> effect_result.RunEffectResult:
        return effect_result.RunEffectResult(
            problems=tuple(self._boundary.problems),
            observed_state=tuple(self.observed_state),
            baseline_state=tuple(self.baseline_state),
            final_state=tuple(self.final_state),
            domain_execution_attempts=tuple(self.domain_execution_attempts),
            indeterminate=self._boundary.indeterminate,
            cancelled=self.cancelled,
            domain_failure=self.domain_failure,
            coverage_failure=self.coverage_failure,
            interruption=self._boundary.interruption,
        )


__all__ = ["RunEffectInterpreter"]
