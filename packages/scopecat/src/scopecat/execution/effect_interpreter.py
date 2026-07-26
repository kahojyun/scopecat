"""Synchronous coverage orchestration for a provisioned ``RunProgram``.

Concrete compute, instrument, measurement, journal, and lifecycle behavior
lives in the corresponding :mod:`scopecat.execution.effects` components.
This module retains only exact-order coverage and point-lifecycle sequencing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import scopecat.execution.effect_result as effect_result
from scopecat.execution.effects.compute import (
    ComputeEffectExecutor,
    EffectEvaluationFrame,
    PointEffectState,
)
from scopecat.execution.effects.dispatch import PointEffectDispatcher
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.effects.lifecycle import DriverLifecycle
from scopecat.execution.effects.measurement import MeasurementEffectExecutor
from scopecat.execution.effects.state import StateEffectExecutor
from scopecat.execution.local.program import (
    ApplyStateOperation,
    ComputeOperation,
)
from scopecat.execution.points import AdmittedPointLedger
from scopecat.execution.program import (
    RunCoverageBlock,
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
    RunOperation,
)
from scopecat.graph.values import ValueId
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import ProblemPhase
from scopecat.records.artifact import CommandPayload
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import InstrumentDriver
from scopecat.sdk.journal import ExecutionJournal, ExecutionJournalError


class _CapturedDomainEffectFailure(Exception):
    """Stop the operation loop after retaining a structured domain failure."""


class _CapturedCoverageFailure(Exception):
    """Stop after retaining a failure from the coverage consumer."""


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
        resource_order: Sequence[str],
        drivers: Mapping[str, InstrumentDriver],
        journal: ExecutionJournal,
        coverage_observer: effect_result.CoverageMeasurementObserver | None = None,
    ) -> None:
        self.run_id = run_id
        self.point_ledger = AdmittedPointLedger(
            coordinate_ids=tuple(coordinate_ids),
        )
        self.logical_points: dict[int, LogicalPointId] = {}
        self.initial_state: list[InstrumentStateSnapshot] = []
        self.final_state: list[InstrumentStateSnapshot] = []
        self.domain_failure: tuple[RunDomainJob, BaseException] | None = None
        self.coverage_failure: BaseException | None = None
        self.run_compute_results: dict[ValueId, object] = {}
        self.run_payloads: dict[str, CommandPayload] = {}
        self._point_states: dict[int, PointEffectState] = {}
        self._active_point_indices: set[int] = set()
        self._terminal_point_indices: set[int] = set()

        driver_map = dict(drivers)
        self._journal = JournaledEffectBoundary(run_id=run_id, journal=journal)
        self._compute = ComputeEffectExecutor(journal=self._journal)
        self._state = StateEffectExecutor(
            drivers=driver_map,
            journal=self._journal,
        )
        self._measurements = MeasurementEffectExecutor(
            drivers=driver_map,
            journal=self._journal,
            coverage_observer=coverage_observer,
        )
        self._dispatch = PointEffectDispatcher(
            compute=self._compute,
            state=self._state,
            measurement=self._measurements,
        )
        self._lifecycle = DriverLifecycle(
            resource_order=resource_order,
            drivers=driver_map,
            journal=self._journal,
        )

    @property
    def current_states(self) -> dict[str, InstrumentStateSnapshot]:
        """Return the accepted state used to reconcile later writes."""

        return self._state.current_states

    def run(
        self,
        operations: Iterable[RunOperation],
    ) -> effect_result.RunEffectResult:
        """Interpret the residual effect sequence exactly in program order."""

        try:
            self.initial_state = self._lifecycle.read_states(phase="initial")
            self._state.current_states = {
                state.instrument_id: state for state in self.initial_state
            }
            for operation in operations:
                if bool(self._journal.problems):
                    break
                match operation:
                    case ComputeOperation():
                        self._execute_run_compute(operation)
                    case RunCoverageBlock():
                        admitted = self.point_ledger.admit(operation.points)
                        self.logical_points.update(
                            (point.ordinal, point.logical_id) for point in admitted
                        )
                        self._execute_coverage_block_effects(operation)
            if (
                not bool(self._journal.problems)
                and self.domain_failure is None
                and self._terminal_point_indices != set(self.logical_points)
            ):
                raise AssertionError("run ended without completing every logical point")
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
            self._lifecycle.finalize()
            self.final_state = self._lifecycle.read_states(phase="terminal")
        return self._result()

    def _execute_coverage_block_effects(self, block: RunCoverageBlock) -> None:
        for operation in block.operations:
            if isinstance(operation, RunCoverageCheckpoint):
                self._commit_coverage_checkpoint(block, operation)
                continue
            self._execute_covered_operation(operation)
            if bool(self._journal.problems):
                return
        remaining = tuple(
            point_index
            for point_index in block.point_indices
            if point_index not in self._terminal_point_indices
        )
        if remaining:
            self._commit_coverage(block, remaining)

    def _commit_coverage_checkpoint(
        self,
        block: RunCoverageBlock,
        checkpoint: RunCoverageCheckpoint,
    ) -> None:
        if checkpoint.point_index not in block.point_indices:
            raise AssertionError("coverage checkpoint escapes its effect block")
        self._commit_coverage(block, (checkpoint.point_index,))

    def _commit_coverage(
        self,
        block: RunCoverageBlock,
        point_indices: tuple[int, ...],
    ) -> None:
        self._complete_coverage(point_indices)
        try:
            self._measurements.commit_coverage(block, point_indices)
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
        representative = self._point_state(covered.point_indices[0])
        self._dispatch.execute(representative, covered.operation)
        if bool(self._journal.problems):
            return
        if not isinstance(covered.operation, ComputeOperation):
            if len(covered.point_indices) > 1 and not isinstance(
                covered.operation,
                ApplyStateOperation,
            ):
                raise AssertionError(
                    "only pure compute and stable state may cover multiple points"
                )
            return
        result_id = covered.operation.result.id
        result = representative.compute_results[result_id]
        payload = (
            None
            if covered.operation.payload_slot is None
            else representative.payloads[covered.operation.payload_slot.id]
        )
        for point_index in covered.point_indices[1:]:
            state = self._point_state(point_index)
            state.compute_results[result_id] = result
            if payload is not None:
                state.payloads[payload.id] = payload

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
                semantic_operation_id=job.id,
                run_id=self.run_id,
                journal=self._journal.execution_journal,
            )
        except BaseException as error:
            self.domain_failure = (job, error)
            pending = tuple(sorted(self._active_point_indices))
            if pending:
                self._complete_coverage(pending)
            raise _CapturedDomainEffectFailure(job.id) from error
        self._measurements.values.extend(values)

    def _execute_run_compute(self, operation: ComputeOperation) -> None:
        frame = EffectEvaluationFrame(
            compute_results=dict(self.run_compute_results),
            payloads=dict(self.run_payloads),
        )
        self._compute.execute(frame, (operation,))
        self.run_compute_results.update(frame.compute_results)
        self.run_payloads.update(frame.payloads)

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
            compute_results=dict(self.run_compute_results),
            payloads=dict(self.run_payloads),
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

    def _result(self) -> effect_result.RunEffectResult:
        return effect_result.RunEffectResult(
            problems=tuple(self._journal.problems),
            initial_state=tuple(self.initial_state),
            final_state=tuple(self.final_state),
            admitted_points=self.point_ledger.points,
            indeterminate=self._journal.indeterminate,
            domain_failure=self.domain_failure,
            coverage_failure=self.coverage_failure,
            interruption=self._journal.interruption,
        )


__all__ = ["RunEffectInterpreter"]
