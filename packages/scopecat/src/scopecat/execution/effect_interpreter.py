"""Synchronous, exact-order interpreter for a provisioned RunProgram.

The interpreter consumes bounded coverage once, records intent before each
consequential invocation, and retains observed effect facts. Keeping rejected
and uncertain outcomes distinct prevents unsafe retries. Measurement candidates
are closed at coverage checkpoints so completed prefixes can be committed and
released promptly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue

from scopecat.compiler.semantic.model import ValueId
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.events import TransitionRecorder, payload_summary
from scopecat.execution.local.program import (
    ApplyStateOperation,
    BoundInput,
    CollectOperation,
    ComputeOperation,
    LocalOperation,
)
from scopecat.execution.local.receipts import (
    apply_receipt_evidence as _apply_receipt_evidence,
)
from scopecat.execution.local.receipts import (
    collect_receipt_evidence as _collect_receipt_evidence,
)
from scopecat.execution.local.receipts import (
    command_evidence as _command_evidence,
)
from scopecat.execution.local.receipts import (
    validate_readback,
)
from scopecat.execution.points import AdmittedPointLedger, RunPoint
from scopecat.execution.ports.journal import (
    ExecutionJournalError,
)
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat.execution.program import (
    RunCoverageBlock,
    RunCoverageCheckpoint,
    RunCoverageEffect,
    RunCoveredOperation,
    RunDomainJob,
    RunOperation,
)
from scopecat.kernel.content_identity import (
    content_fingerprint,
    stable_content_hash,
)
from scopecat.kernel.payloads import unwrap_payload_values
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
)
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.value_validation import coerce_literal
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.artifact import CommandPayload
from scopecat.records.execution_journal import (
    ExecutionEffect,
    ExecutionStage,
    ExecutionTransition,
    JournalEntryState,
)
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    InstrumentDriver,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    apply_state_command_to_snapshot,
)

logger = logging.getLogger(__name__)


class _CapturedDomainEffectFailure(Exception):
    """Stop the operation loop after retaining a structured domain failure."""


class _CapturedCoverageFailure(Exception):
    """Stop after retaining a failure from the coverage consumer."""


type CoverageMeasurementObserver = Callable[
    [RunCoverageBlock, tuple[MeasurementValueCandidate, ...]],
    None,
]


@dataclass(frozen=True, slots=True)
class RunEffectResult:
    """Facts observed while interpreting effects; not a terminal run outcome."""

    problems: tuple[Problem, ...]
    initial_state: tuple[InstrumentStateSnapshot, ...]
    final_state: tuple[InstrumentStateSnapshot, ...]
    admitted_points: tuple[RunPoint, ...] = ()
    indeterminate: bool = False
    domain_failure: tuple[RunDomainJob, BaseException] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    coverage_failure: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    interruption: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(slots=True)
class _MutablePointStats:
    compute_evaluated_node_count: int = 0
    compute_payload_count: int = 0


@dataclass(slots=True, kw_only=True)
class _EvaluationFrame:
    event_point_index: int | None = None
    stats: _MutablePointStats = field(default_factory=_MutablePointStats)
    compute_results: dict[ValueId, object] = field(default_factory=dict)
    payloads: dict[str, CommandPayload] = field(default_factory=dict)


@dataclass(slots=True)
class _PointEvaluationState(_EvaluationFrame):
    point_index: int
    logical_id: LogicalPointId
    product_use_ids: set[ProductUseId] = field(default_factory=set)


class RunEffectInterpreter:
    """Execute provisioned host operations with fail-closed journaling.

    The caller must create the durable run skeleton before invoking ``run``.
    The executor never infers parallelism from independent-looking hardware
    operations; operation order is part of the program semantics. Terminal
    certainty and run outcome are derived by the outer run boundary from the
    facts returned here.
    """

    def __init__(
        self,
        *,
        run_id: str,
        coordinate_ids: Sequence[str],
        resource_order: Sequence[str],
        drivers: Mapping[str, InstrumentDriver],
        recorder: TransitionRecorder,
        payload_observer: Callable[[CommandPayload], None] | None = None,
        coverage_observer: CoverageMeasurementObserver | None = None,
    ) -> None:
        self.run_id = run_id
        self.point_ledger = AdmittedPointLedger(
            coordinate_ids=tuple(coordinate_ids),
        )
        self.logical_points: dict[int, LogicalPointId] = {}
        self.resource_order = tuple(resource_order)
        self.drivers = dict(drivers)
        self.recorder = recorder
        self.payload_observer = payload_observer
        self.coverage_observer = coverage_observer
        self.problems: list[Problem] = []
        self.initial_state: list[InstrumentStateSnapshot] = []
        self.final_state: list[InstrumentStateSnapshot] = []
        self.current_states: dict[str, InstrumentStateSnapshot] = {}
        self.measurement_values: list[MeasurementValueCandidate] = []
        self.domain_failure: tuple[RunDomainJob, BaseException] | None = None
        self.coverage_failure: BaseException | None = None
        self.run_compute_results: dict[ValueId, object] = {}
        self.run_payloads: dict[str, CommandPayload] = {}
        self._indeterminate = False
        self._interruption: BaseException | None = None
        self._point_states: dict[int, _PointEvaluationState] = {}
        self._active_point_indices: set[int] = set()
        self._terminal_point_indices: set[int] = set()

    def run(self, operations: Iterable[RunOperation]) -> RunEffectResult:
        """Interpret the residual effect sequence exactly in program order."""

        try:
            self.initial_state = self._read_states(phase="initial")
            self.current_states = {
                state.instrument_id: state for state in self.initial_state
            }
            for operation in operations:
                if bool(self.problems):
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
                not bool(self.problems)
                and self.domain_failure is None
                and self._terminal_point_indices != set(self.logical_points)
            ):
                raise AssertionError("run ended without completing every logical point")
        except ExecutionJournalError as error:
            self.problems.append(
                self._problem(
                    "execution_journal_commit_failed",
                    str(error),
                    phase=ProblemPhase.PERSISTENCE,
                )
            )
        except _CapturedDomainEffectFailure:
            pass
        except _CapturedCoverageFailure:
            pass
        except Exception as error:  # Defensive interpreter boundary.
            self.problems.append(
                self._problem_from_exception(
                    "run_effect_interpretation_failed",
                    "run effect interpretation failed",
                    error,
                )
            )
        except BaseException as error:
            self._record_interruption(error)
        finally:
            if self._active_point_indices:
                self._complete_coverage(
                    tuple(sorted(self._active_point_indices)), failed=True
                )
            self._finalize_drivers()
            # Terminal state is deliberately captured after abort/cleanup.
            self._capture_terminal_states()
        return self._result()

    def _execute_coverage_block_effects(self, block: RunCoverageBlock) -> None:
        for operation in block.operations:
            if isinstance(operation, RunCoverageCheckpoint):
                self._commit_coverage_checkpoint(block, operation)
                continue
            self._execute_covered_operation(operation)
            if bool(self.problems):
                return
        remaining = tuple(
            point_index
            for point_index in block.point_indices
            if point_index not in self._terminal_point_indices
        )
        if remaining:
            self._commit_coverage(
                block,
                remaining,
            )

    def _commit_coverage_checkpoint(
        self,
        block: RunCoverageBlock,
        checkpoint: RunCoverageCheckpoint,
    ) -> None:
        if checkpoint.point_index not in block.point_indices:
            raise AssertionError("coverage checkpoint escapes its effect block")
        self._commit_coverage(
            block,
            (checkpoint.point_index,),
        )

    def _commit_coverage(
        self,
        block: RunCoverageBlock,
        point_indices: tuple[int, ...],
    ) -> None:
        self._complete_coverage(point_indices, failed=False)
        if self.coverage_observer is None:
            return
        point_index_set = frozenset(point_indices)
        candidates = tuple(
            candidate
            for candidate in self.measurement_values
            if candidate.logical_point_id.logical_ordinal in point_index_set
        )
        points = tuple(
            point for point in block.points if point.ordinal in point_indices
        )
        committed = RunCoverageBlock(points, ())
        try:
            self.coverage_observer(committed, candidates)
        except BaseException as error:
            self.coverage_failure = error
            raise _CapturedCoverageFailure from error
        self.measurement_values[:] = (
            candidate
            for candidate in self.measurement_values
            if candidate.logical_point_id.logical_ordinal not in point_index_set
        )

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
        self._execute_point_effect(representative, covered.operation)
        if bool(self.problems):
            return
        if not isinstance(covered.operation, ComputeOperation):
            if len(covered.point_indices) > 1 and not isinstance(
                covered.operation, ApplyStateOperation
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
                journal=self.recorder.journal,
            )
        except BaseException as error:
            self.domain_failure = (job, error)
            pending = tuple(sorted(self._active_point_indices))
            if pending:
                self._complete_coverage(pending, failed=True)
            raise _CapturedDomainEffectFailure(job.id) from error
        self.measurement_values.extend(values)

    def _execute_run_compute(self, operation: ComputeOperation) -> None:
        frame = _EvaluationFrame(
            compute_results=dict(self.run_compute_results),
            payloads=dict(self.run_payloads),
        )
        self._execute_compute_operations(frame, (operation,))
        self.run_compute_results.update(frame.compute_results)
        self.run_payloads.update(frame.payloads)

    def _point_state(self, point_index: int) -> _PointEvaluationState:
        if point_index in self._terminal_point_indices:
            raise AssertionError("point effect follows point completion")
        state = self._point_states.get(point_index)
        if state is not None:
            return state
        try:
            logical_id = self.logical_points[point_index]
        except KeyError as error:
            raise AssertionError("point effect references an unknown point") from error
        state = _PointEvaluationState(
            point_index=point_index,
            logical_id=logical_id,
            event_point_index=point_index,
            compute_results=dict(self.run_compute_results),
            payloads=dict(self.run_payloads),
        )
        self._point_states[point_index] = state
        self._active_point_indices.add(point_index)
        return state

    def _execute_point_effect(
        self,
        frame: _PointEvaluationState,
        operation: LocalOperation,
    ) -> None:
        match operation:
            case ComputeOperation():
                self._execute_compute_operations(frame, (operation,))
            case ApplyStateOperation():
                self._apply_state_operation(frame, operation)
            case CollectOperation():
                self._collect_operation(frame, operation)

    def _complete_coverage(
        self, point_indices: tuple[int, ...], *, failed: bool
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
        self.recorder.observe(
            self._entry(
                operation_id=f"coverage.{point_indices[0]}-{point_indices[-1]}",
                stage="point",
                effect="pure",
                state="failed" if failed else "completed",
                evidence={"point_indices": list(point_indices)},
            )
        )

    def _execute_compute_operations(
        self,
        frame: _EvaluationFrame,
        operations: Sequence[ComputeOperation],
    ) -> None:
        for operation in operations:
            entry = self._entry(
                operation_id=operation.operation_id,
                stage="compute",
                effect="pure",
                state="started",
                point_index=frame.event_point_index,
                evidence={
                    "semantic_operation_id": operation.semantic_operation_id,
                    "implementation_id": operation.implementation_id,
                    **_dependency_summary(operation.dependencies),
                },
            )
            self.recorder.observe(entry)
            try:
                inputs = {
                    name: (
                        value.value
                        if isinstance(value, BoundInput)
                        else frame.compute_results[value.value_id]
                    )
                    for name, value in operation.inputs.items()
                }
                raw_result = operation.kernel(**inputs)
                result = unwrap_payload_values(
                    coerce_literal(
                        operation.result.value_type,
                        raw_result,
                        path=("operations", operation.operation_id, "output"),
                    )
                )
                if operation.payload_slot is not None:
                    fingerprint = content_fingerprint(result)
                    content_hash = stable_content_hash(fingerprint)
                else:
                    content_hash = None
            except Exception as error:
                problem = self._problem_from_exception(
                    "compute_operation_failed",
                    f"compute operation {operation.operation_id} failed",
                    error,
                    operation_id=operation.operation_id,
                    point_index=frame.event_point_index,
                )
                self.problems.append(problem)
                self.recorder.observe(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                return
            frame.compute_results[operation.result.id] = result
            frame.stats.compute_evaluated_node_count += 1
            if operation.payload_slot is not None:
                slot = operation.payload_slot
                frame.payloads[slot.id] = CommandPayload(
                    id=slot.id,
                    schema_id=slot.schema_id,
                    content_hash=content_hash,
                    operation_id=operation.operation_id,
                    semantic_operation_id=operation.semantic_operation_id,
                    implementation_id=operation.implementation_id,
                    point_index=frame.event_point_index,
                    payload=result,
                )
                frame.stats.compute_payload_count += 1
                self._observe_payload(frame.payloads[slot.id])
            self.recorder.observe(
                entry.model_copy(
                    update={
                        "state": "completed",
                        "evidence": {
                            "semantic_operation_id": operation.semantic_operation_id,
                            "implementation_id": operation.implementation_id,
                            **_dependency_summary(operation.dependencies),
                            **(
                                {
                                    "payload_id": operation.payload_slot.id,
                                    "schema_id": operation.payload_slot.schema_id,
                                    "content_hash": content_hash,
                                    **payload_summary(result),
                                }
                                if operation.payload_slot is not None
                                else {}
                            ),
                        },
                    }
                )
            )

    def _apply_state_operation(
        self,
        frame: _PointEvaluationState,
        operation: ApplyStateOperation,
    ) -> bool:
        current = self.current_states.get(operation.instrument_id)
        if current is None:
            self.problems.append(
                self._problem(
                    "missing_current_state",
                    f"missing current state for {operation.instrument_id}",
                    operation_id=operation.operation_id,
                    point_index=frame.point_index,
                    instrument_id=operation.instrument_id,
                )
            )
            return False
        fields, skipped_count = _changed_state_fields(operation, current=current)
        entry = self._entry(
            operation_id=operation.operation_id,
            stage="apply_state",
            effect="state_write",
            state="started",
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "field_count": len(fields),
                "skipped_field_count": skipped_count,
            },
        )
        if not fields:
            self.recorder.observe(
                entry.model_copy(
                    update={
                        "state": "skipped",
                        "evidence": self._state_event_summary(
                            frame,
                            entry.evidence,
                            changed_field_count=0,
                            state_command_count=0,
                            payload_count=0,
                        ),
                    }
                )
            )
            return True
        command = InstrumentStateCommand(
            operation_id=operation.operation_id,
            instrument_id=operation.instrument_id,
            fields=fields,
            payloads=_referenced_payloads(fields, frame.payloads),
        )
        entry = entry.model_copy(
            update={
                "evidence": {
                    **entry.evidence,
                    **_command_evidence(command),
                }
            }
        )
        driver = self.drivers[operation.instrument_id]
        receipt = self._invoke_journaled_effect(
            entry,
            lambda: driver.apply_state(command),
            unknown_code="instrument_apply_unknown",
            unknown_message=(
                f"instrument apply outcome is unknown for {operation.instrument_id}"
            ),
            unknown_evidence=self._state_event_summary(
                frame,
                entry.evidence,
                changed_field_count=0,
                state_command_count=0,
                payload_count=0,
            ),
        )
        if receipt is None:
            return False
        return self._complete_apply_receipt(
            frame=frame,
            operation=operation,
            entry=entry,
            current=current,
            fields=fields,
            command=command,
            receipt=receipt,
            receipt_evidence=_apply_receipt_evidence(receipt),
        )

    def _complete_apply_receipt(
        self,
        *,
        frame: _PointEvaluationState,
        operation: ApplyStateOperation,
        entry: ExecutionTransition,
        current: InstrumentStateSnapshot,
        fields: list[InstrumentStateCommandField],
        command: InstrumentStateCommand,
        receipt: ApplyReceipt,
        receipt_evidence: dict[str, JsonValue],
    ) -> bool:
        accepted, receipt_problems = self._accept_receipt(
            entry,
            status=receipt.status,
            success_status="applied",
            problems=receipt.problems,
            evidence={
                **self._state_event_summary(
                    frame,
                    entry.evidence,
                    changed_field_count=0,
                    state_command_count=0,
                    payload_count=0,
                ),
                "receipt_status": receipt.status,
                **receipt_evidence,
            },
        )
        if not accepted:
            # Never advance predicted state or continue to another resource.
            return False
        next_state = receipt.state or apply_state_command_to_snapshot(current, command)
        if next_state.instrument_id != operation.instrument_id:
            problem = self._problem(
                "instrument_apply_state_mismatch",
                "apply receipt state belongs to a different instrument",
                operation_id=operation.operation_id,
                point_index=frame.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._indeterminate = True
            self._commit_after_effect(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "problems": (problem,),
                        "evidence": {
                            **self._state_event_summary(
                                frame,
                                entry.evidence,
                                changed_field_count=0,
                                state_command_count=0,
                                payload_count=0,
                            ),
                            **receipt_evidence,
                        },
                    }
                )
            )
            return False
        self.current_states[operation.instrument_id] = next_state.model_copy(deep=True)
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "completed",
                    "problems": receipt_problems,
                    "evidence": {
                        **self._state_event_summary(
                            frame,
                            entry.evidence,
                            changed_field_count=len(fields),
                            state_command_count=1,
                            payload_count=len(command.payloads),
                        ),
                        "receipt_status": receipt.status,
                        **receipt_evidence,
                    },
                }
            )
        )
        return True

    @staticmethod
    def _state_event_summary(
        frame: _PointEvaluationState,
        base: Mapping[str, JsonValue],
        *,
        changed_field_count: int,
        state_command_count: int,
        payload_count: int,
    ) -> dict[str, JsonValue]:
        return {
            **base,
            "compute_evaluated_node_count": (frame.stats.compute_evaluated_node_count),
            "compute_payload_count": frame.stats.compute_payload_count,
            "changed_field_count": changed_field_count,
            "skipped_field_count": base.get("skipped_field_count", 0),
            "state_command_count": state_command_count,
            "payload_count": payload_count,
        }

    def _collect_operation(
        self,
        frame: _PointEvaluationState,
        operation: CollectOperation,
    ) -> bool:
        command = operation.command.model_copy(deep=True)
        command_evidence = _command_evidence(command)
        entry = self._entry(
            operation_id=operation.operation_id,
            stage="collect",
            effect="acquisition",
            state="started",
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "request_count": len(operation.command.requests),
                "product_ids": [item.id for item in operation.command.requests],
                **command_evidence,
            },
        )
        receipt = self._invoke_journaled_effect(
            entry,
            lambda: self.drivers[operation.instrument_id].collect(command),
            unknown_code="instrument_collect_unknown",
            unknown_message=(
                "instrument collection outcome is unknown for "
                f"{operation.instrument_id}"
            ),
        )
        if receipt is None:
            return False
        receipt_evidence = _collect_receipt_evidence(receipt)
        accepted, receipt_problems = self._accept_receipt(
            entry,
            status=receipt.status,
            success_status="collected",
            problems=receipt.problems,
            evidence={**entry.evidence, **receipt_evidence},
        )
        if not accepted:
            return False
        assert receipt.readback is not None  # noqa: S101
        readback = receipt.readback
        validation_problems = contextualize_problems(
            validate_readback(operation, readback),
            run_id=self.run_id,
            operation_id=operation.operation_id,
            point_index=frame.point_index,
            instrument_id=operation.instrument_id,
        )
        operation_problems = (*receipt_problems, *validation_problems)
        self.problems.extend(validation_problems)
        if not bool(operation_problems):
            self._merge_readback(frame, operation, readback)
        failed = bool(operation_problems)
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "failed" if failed else "completed",
                    "problems": operation_problems,
                    "evidence": {
                        **entry.evidence,
                        **receipt_evidence,
                        "value_count": len(readback.values),
                    },
                }
            )
        )
        return not failed

    def _merge_readback(
        self,
        frame: _PointEvaluationState,
        operation: CollectOperation,
        readback: InstrumentReadback,
    ) -> None:
        bindings = {
            binding.provider_key: binding for binding in operation.result_bindings
        }
        for provider_key, value in readback.values.items():
            binding = bindings.get(provider_key)
            if binding is None:
                self.problems.append(
                    self._problem(
                        "instrument_unexpected_product",
                        (
                            f"instrument {operation.instrument_id} returned "
                            f"unexpected product {provider_key}"
                        ),
                        operation_id=operation.operation_id,
                        point_index=frame.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            for product_use_id in binding.product_use_ids:
                if product_use_id in frame.product_use_ids:
                    self.problems.append(
                        self._problem(
                            "instrument_duplicate_product_use",
                            "point received more than one result for logical "
                            f"product use {product_use_id.value}",
                            operation_id=operation.operation_id,
                            point_index=frame.point_index,
                            instrument_id=operation.instrument_id,
                        )
                    )
                    continue
                frame.product_use_ids.add(product_use_id)
                self.measurement_values.append(
                    MeasurementValueCandidate(
                        logical_point_id=frame.logical_id,
                        product_use_id=product_use_id,
                        value=value,
                    )
                )

    def _read_states(
        self, *, phase: Literal["initial", "terminal"]
    ) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        for instrument_id in self.resource_order:
            operation_id = f"lifecycle.{phase}-read-state.{instrument_id}"
            transition_stage: ExecutionStage = (
                "terminal_readback" if phase == "terminal" else "initial_readback"
            )
            entry = self._entry(
                operation_id=operation_id,
                stage=transition_stage,
                effect="read",
                state="started",
                instrument_id=instrument_id,
            )
            self.recorder.observe(entry)
            try:
                state = self.drivers[instrument_id].read_state().model_copy(deep=True)
                if state.instrument_id != instrument_id:
                    raise ValueError("read state belongs to a different instrument")
            except Exception as error:
                problem = self._problem_from_exception(
                    "instrument_readback_failed",
                    f"instrument {phase} readback failed for {instrument_id}",
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.problems.append(problem)
                failed_entry = entry.model_copy(
                    update={"state": "failed", "problems": (problem,)}
                )
                self.recorder.observe(failed_entry)
                continue
            except BaseException as error:
                problem = self._record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.recorder.observe(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            states.append(state)
            completed_entry = entry.model_copy(update={"state": "completed"})
            self.recorder.observe(completed_entry)
        return states

    def _finalize_drivers(self) -> None:
        action = "abort" if bool(self.problems) else "cleanup"
        used = set(self.resource_order)
        extras = tuple(sorted(set(self.drivers) - used))
        managed_order = (
            *extras,
            *(
                instrument_id
                for instrument_id in self.resource_order
                if instrument_id in self.drivers
            ),
        )
        for instrument_id in reversed(managed_order):
            operation_id = f"lifecycle.{action}.{instrument_id}"
            entry = self._entry(
                operation_id=operation_id,
                stage=action,
                effect="lifecycle",
                state="started",
                instrument_id=instrument_id,
            )
            # Safety finalization proceeds even if the journal itself is damaged.
            self._commit_transition_best_effort(entry)

            try:
                getattr(self.drivers[instrument_id], action)()
            except Exception as error:
                problem = self._problem_from_exception(
                    f"instrument_{action}_failed",
                    f"instrument {action} failed for {instrument_id}",
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self.problems.append(problem)
                self._commit_transition_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            except BaseException as error:
                problem = self._record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self._commit_transition_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            self._commit_transition_best_effort(
                entry.model_copy(update={"state": "completed"})
            )

    def _capture_terminal_states(self) -> None:
        self.final_state = self._read_states(phase="terminal")

    def _entry(
        self,
        *,
        operation_id: str,
        stage: ExecutionStage,
        effect: ExecutionEffect,
        state: JournalEntryState,
        point_index: int | None = None,
        instrument_id: str | None = None,
        evidence: Mapping[str, JsonValue] | None = None,
    ) -> ExecutionTransition:
        return ExecutionTransition(
            run_id=self.run_id,
            operation_id=operation_id,
            stage=stage,
            effect=effect,
            state=state,
            point_index=point_index,
            instrument_id=instrument_id,
            evidence=dict(evidence or {}),
        )

    def _invoke_journaled_effect[ReceiptT](
        self,
        entry: ExecutionTransition,
        invoke: Callable[[], ReceiptT],
        *,
        unknown_code: str,
        unknown_message: str,
        unknown_evidence: Mapping[str, JsonValue] | None = None,
        after_intent: Callable[[], None] | None = None,
    ) -> ReceiptT | None:
        """Persist an effect intent, invoke it once, and close unknown outcomes."""

        self.recorder.commit(entry)
        if after_intent is not None:
            after_intent()
        try:
            return invoke()
        except Exception as error:
            self._indeterminate = True
            problem = self._problem_from_exception(
                unknown_code,
                unknown_message,
                error,
                operation_id=entry.operation_id,
                point_index=entry.point_index,
                instrument_id=entry.instrument_id,
            )
            self.problems.append(problem)
        except BaseException as error:
            self._indeterminate = True
            problem = self._record_interruption(
                error,
                operation_id=entry.operation_id,
                point_index=entry.point_index,
                instrument_id=entry.instrument_id,
            )
        self._commit_transition_best_effort(
            entry.model_copy(
                update={
                    "state": "unknown",
                    "problems": (problem,),
                    "evidence": dict(unknown_evidence or entry.evidence),
                }
            )
        )
        return None

    def _accept_receipt(
        self,
        entry: ExecutionTransition,
        *,
        status: str,
        success_status: str,
        problems: Sequence[Problem],
        evidence: Mapping[str, JsonValue],
    ) -> tuple[bool, tuple[Problem, ...]]:
        """Contextualize a driver receipt and close non-success outcomes."""

        receipt_problems = contextualize_problems(
            problems,
            run_id=self.run_id,
            operation_id=entry.operation_id,
            point_index=entry.point_index,
            instrument_id=entry.instrument_id,
        )
        self.problems.extend(receipt_problems)
        if status == success_status:
            return True, receipt_problems
        if status == "unknown":
            self._indeterminate = True
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "unknown" if status == "unknown" else "failed",
                    "problems": receipt_problems,
                    "evidence": dict(evidence),
                }
            )
        )
        return False, receipt_problems

    def _commit_after_effect(self, entry: ExecutionTransition) -> None:
        try:
            self.recorder.commit(entry)
        except Exception:
            self._indeterminate = True
            raise

    def _commit_transition_best_effort(self, entry: ExecutionTransition) -> None:
        """Record a transition without allowing evidence failure to block safety."""

        try:
            self.recorder.commit(entry)
        except Exception as error:
            self._indeterminate = True
            self.problems.append(
                self._problem_from_exception(
                    "execution_journal_commit_failed",
                    f"failed to journal {entry.operation_id}",
                    error,
                    operation_id=entry.operation_id,
                    point_index=entry.point_index,
                    instrument_id=entry.instrument_id,
                    phase=ProblemPhase.PERSISTENCE,
                )
            )
        except BaseException as error:
            self._indeterminate = True
            self._record_interruption(error, operation_id=entry.operation_id)

    def _observe_payload(self, payload: CommandPayload) -> None:
        if self.payload_observer is None:
            return
        try:
            self.payload_observer(payload)
        except BaseException:
            logger.exception(
                "execution payload observer failed",
                extra={"run_id": self.run_id, "payload_id": payload.id},
            )

    def _record_interruption(
        self,
        error: BaseException,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
    ) -> Problem:
        if self._interruption is None:
            self._interruption = error
        problem = self._problem(
            "execution_interrupted",
            f"execution interrupted by {type(error).__name__}",
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            details={
                "exception_type": f"{type(error).__module__}.{type(error).__qualname__}"
            },
        )
        self.problems.append(problem)
        return problem

    def _problem(
        self,
        code: str,
        message: str,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
        details: Mapping[str, object] | None = None,
    ) -> Problem:
        return runtime_problem(
            code,
            message,
            run_id=self.run_id,
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            phase=phase,
            details=details,
        )

    def _problem_from_exception(
        self,
        code: str,
        message: str,
        error: Exception,
        *,
        operation_id: str | None = None,
        point_index: int | None = None,
        instrument_id: str | None = None,
        phase: ProblemPhase = ProblemPhase.EXECUTION,
    ) -> Problem:
        return problem_from_exception(
            code,
            message,
            run_id=self.run_id,
            error=error,
            operation_id=operation_id,
            point_index=point_index,
            instrument_id=instrument_id,
            phase=phase,
        )

    def _result(self) -> RunEffectResult:
        return RunEffectResult(
            problems=tuple(self.problems),
            initial_state=tuple(self.initial_state),
            final_state=tuple(self.final_state),
            admitted_points=self.point_ledger.points,
            indeterminate=self._indeterminate,
            domain_failure=self.domain_failure,
            coverage_failure=self.coverage_failure,
            interruption=self._interruption,
        )


def _changed_state_fields(
    operation: ApplyStateOperation,
    *,
    current: InstrumentStateSnapshot,
) -> tuple[list[InstrumentStateCommandField], int]:
    current_by_key = {
        _execution_state_target_identity(
            field.capability_id,
            field.field_path,
            field.entity_ids,
            field.channel_bindings,
        ): field.value
        for field in current.fields
    }
    fields: list[InstrumentStateCommandField] = []
    skipped = 0
    for target in operation.targets:
        key = _execution_state_target_identity(
            target.capability_id,
            target.field_path,
            target.entity_ids,
            target.channel_bindings,
        )
        field = target.command_field(resource_id=operation.instrument_id)
        if current_by_key.get(key) == target.value:
            skipped += 1
            continue
        fields.append(field)
    return fields, skipped


def _execution_state_target_identity(
    capability_id: str,
    field_path: str,
    entity_ids: Sequence[str],
    channel_bindings: Sequence[CommandChannelBinding],
) -> tuple[object, ...]:
    return (
        capability_id,
        field_path,
        tuple(entity_ids),
        tuple(
            (
                binding.entity_id,
                binding.channel_id,
                binding.line_id,
                binding.capability,
                tuple(sorted(binding.group_ids)),
            )
            for binding in channel_bindings
        ),
    )


def _referenced_payloads(
    fields: Sequence[InstrumentStateCommandField],
    payloads: Mapping[str, CommandPayload],
) -> dict[str, CommandPayload]:
    referenced: dict[str, CommandPayload] = {}
    for target_field in fields:
        value = target_field.value.root
        if not isinstance(value, PayloadRef):
            continue
        payload = payloads.get(value.payload_id)
        if payload is not None:
            referenced[payload.id] = payload
    return referenced


def _dependency_summary(
    dependencies: Mapping[str, tuple[str, ...]],
) -> dict[str, JsonValue]:
    if not dependencies:
        return {}
    return {
        "dependencies": {name: list(values) for name, values in dependencies.items()}
    }


__all__ = [
    "RunEffectInterpreter",
    "RunEffectResult",
]
