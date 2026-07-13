"""Small synchronous interpreter for :mod:`scopecat._execution.program`."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from pydantic import BaseModel, JsonValue

from scopecat._content_identity import (
    content_fingerprint,
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat._execution.events import payload_summary
from scopecat._execution.journal import (
    CollectionChunk,
    CollectionCommitter,
    CommittedPayloadEvidence,
    ExecutionEffect,
    ExecutionJournal,
    ExecutionJournalError,
    ExecutionStage,
    ExecutionTransition,
    JournalEntryState,
    MeasurementCommitter,
    PayloadEvidence,
    PayloadEvidenceCommitter,
)
from scopecat._execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat._execution.program import (
    ApplyStateOperation,
    ApplyStateStage,
    BoundInput,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeStage,
    ExecutionProgram,
    PointProgram,
    ResourceClaim,
)
from scopecat.instruments.sdk import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    validate_state_command,
)
from scopecat.models.artifact import CommandPayload
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunCertainty, RunResult, RunStatus
from scopecat.models.state import PayloadRef
from scopecat.models.value import PayloadValue
from scopecat.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementRecord,
    MeasurementValue,
)
from scopecat.units import compatible_units
from scopecat.value_validation import coerce_literal

logger = logging.getLogger(__name__)


class ResourceLeaseManager(Protocol):
    """Acquire all claims before any driver interaction begins."""

    def acquire(
        self, claims: tuple[ResourceClaim, ...]
    ) -> AbstractContextManager[None]: ...


class NoopResourceLeaseManager:
    def acquire(
        self, claims: tuple[ResourceClaim, ...]
    ) -> AbstractContextManager[None]:
        del claims
        return nullcontext()


@dataclass(frozen=True, slots=True)
class ExecutionPointStats:
    point_index: int
    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    state_payload_count: int = 0
    compute_evaluated_node_count: int = 0
    compute_reused_node_count: int = 0
    compute_payload_count: int = 0
    acquired_record_count: int = 0


@dataclass(frozen=True, slots=True)
class PointExecutionResult:
    point_index: int
    point_uid: str
    result: Literal["succeeded", "failed"]
    stats: ExecutionPointStats


@dataclass(frozen=True, slots=True)
class ExecutionEngineResult:
    """Complete in-memory result; durable evidence is committed incrementally."""

    run_id: str
    experiment_id: str
    result: RunResult
    certainty: RunCertainty
    termination_reason: str
    problems: tuple[Problem, ...]
    measurements: tuple[MeasurementRecord, ...]
    initial_state: tuple[InstrumentStateSnapshot, ...]
    final_state: tuple[InstrumentStateSnapshot, ...]
    points: tuple[PointExecutionResult, ...]
    interruption: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    @property
    def success(self) -> bool:
        return self.result == "succeeded"

    @property
    def status(self) -> RunStatus:
        if self.result == "succeeded":
            return "completed"
        if self.result == "cancelled":
            return "interrupted"
        return "unknown" if self.certainty == "indeterminate" else "failed"

    @property
    def uncertain(self) -> bool:
        return self.certainty == "indeterminate"

    @property
    def completed_point_count(self) -> int:
        return sum(point.result == "succeeded" for point in self.points)

    @property
    def changed_field_count(self) -> int:
        return sum(point.stats.changed_field_count for point in self.points)

    @property
    def skipped_field_count(self) -> int:
        return sum(point.stats.skipped_field_count for point in self.points)

    @property
    def state_command_count(self) -> int:
        return sum(point.stats.state_command_count for point in self.points)

    @property
    def state_payload_count(self) -> int:
        return sum(point.stats.state_payload_count for point in self.points)

    @property
    def compute_evaluated_node_count(self) -> int:
        return sum(point.stats.compute_evaluated_node_count for point in self.points)

    @property
    def compute_reused_node_count(self) -> int:
        return sum(point.stats.compute_reused_node_count for point in self.points)

    @property
    def compute_payload_count(self) -> int:
        return sum(point.stats.compute_payload_count for point in self.points)


@dataclass(slots=True)
class _MutablePointStats:
    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    state_payload_count: int = 0
    compute_evaluated_node_count: int = 0
    compute_reused_node_count: int = 0
    compute_payload_count: int = 0
    acquired_record_count: int = 0

    def freeze(self, *, point_index: int) -> ExecutionPointStats:
        return ExecutionPointStats(
            point_index=point_index,
            changed_field_count=self.changed_field_count,
            skipped_field_count=self.skipped_field_count,
            state_command_count=self.state_command_count,
            state_payload_count=self.state_payload_count,
            compute_evaluated_node_count=self.compute_evaluated_node_count,
            compute_reused_node_count=self.compute_reused_node_count,
            compute_payload_count=self.compute_payload_count,
            acquired_record_count=self.acquired_record_count,
        )


@dataclass(slots=True)
class _PointFrame:
    point: PointProgram
    stats: _MutablePointStats = field(default_factory=_MutablePointStats)
    compute_results: dict[str, object] = field(default_factory=dict)
    payloads: dict[str, CommandPayload] = field(default_factory=dict)
    observables: dict[str, MeasurementValue] = field(default_factory=dict)
    instrument_ids: list[str] = field(default_factory=list)


class ExecutionEngine:
    """Interpret one closed program with fail-closed journaling.

    The caller must create the durable run skeleton before invoking ``run``.
    This engine never infers parallelism from independent-looking hardware
    operations; stage and operation order are part of the program semantics.
    """

    def __init__(
        self,
        *,
        run_id: str,
        program: ExecutionProgram,
        drivers: Mapping[str, InstrumentDriver],
        journal: ExecutionJournal,
        measurements: MeasurementCommitter,
        readbacks: CollectionCommitter,
        payloads: PayloadEvidenceCommitter,
        descriptions: Mapping[str, InstrumentDescription] | None = None,
        resources: ResourceLeaseManager | None = None,
        payload_observer: Callable[[CommandPayload], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.program = program
        self.drivers = dict(drivers)
        self.journal = journal
        self.measurement_committer = measurements
        self.collection_committer = readbacks
        self.payload_evidence_committer = payloads
        self.descriptions = dict(descriptions or {})
        self.resources = resources or NoopResourceLeaseManager()
        self.payload_observer = payload_observer
        self.problems: list[Problem] = []
        self.initial_state: list[InstrumentStateSnapshot] = []
        self.final_state: list[InstrumentStateSnapshot] = []
        self.current_states: dict[str, InstrumentStateSnapshot] = {}
        self.point_results: list[PointExecutionResult] = []
        self.committed_measurements: list[MeasurementRecord] = []
        self._compute_cache: dict[tuple[str, object], object] = {}
        self._indeterminate = False
        self._interruption: BaseException | None = None

    def run(self) -> ExecutionEngineResult:
        self._validate_drivers()
        if has_blocking_problems(self.problems):
            self._finalize_drivers()
            self._capture_terminal_states()
            return self._result()
        finalized = False
        terminal_read_attempted = False
        try:
            lease = self.resources.acquire(self.program.resource_claims)
            with lease:
                try:
                    self.initial_state = self._read_states(phase="initial")
                    self.current_states = {
                        state.instrument_id: state for state in self.initial_state
                    }
                    if not has_blocking_problems(self.problems):
                        for point in self.program.points:
                            self._execute_point(point)
                            if has_blocking_problems(self.problems):
                                break
                except ExecutionJournalError as error:
                    self.problems.append(
                        self._problem(
                            "execution_journal_commit_failed",
                            str(error),
                            category=ProblemCategory.STORAGE,
                            phase=ProblemPhase.PERSISTENCE,
                        )
                    )
                except Exception as error:  # Defensive engine boundary.
                    self.problems.append(
                        self._problem_from_exception(
                            "execution_engine_failed",
                            "execution engine failed",
                            error,
                        )
                    )
                except BaseException as error:
                    self._record_interruption(error)
                finally:
                    self._finalize_drivers()
                    finalized = True
                    # Terminal state is deliberately captured after abort/cleanup.
                    terminal_read_attempted = True
                    self._capture_terminal_states()
        except Exception as error:
            self.problems.append(
                self._problem_from_exception(
                    "resource_lease_failed",
                    "failed to acquire or release execution resources",
                    error,
                )
            )
            if not finalized:
                self._finalize_drivers()
            if not terminal_read_attempted:
                self._capture_terminal_states()
        except BaseException as error:
            self._record_interruption(error)
            if not finalized:
                self._finalize_drivers()
            if not terminal_read_attempted:
                self._capture_terminal_states()
        return self._result()

    def _validate_drivers(self) -> None:
        for instrument_id in self.program.resource_order:
            if instrument_id in self.drivers:
                continue
            self.problems.append(
                self._problem(
                    "missing_instrument",
                    f"no instrument provided for resource {instrument_id}",
                    instrument_id=instrument_id,
                    category=ProblemCategory.PROVIDER_CONTRACT,
                )
            )

    def _execute_point(self, point: PointProgram) -> None:
        frame = _PointFrame(point=point)
        problem_count_before = len(self.problems)
        point_entry = self._entry(
            operation_id=f"{point.point_uid}.point",
            stage="point",
            effect="pure",
            state="started",
            point_index=point.point_index,
            evidence=cast(
                "dict[str, JsonValue]",
                {
                    "coordinate_ids": sorted(point.coordinates),
                    "compute_step_count": sum(
                        len(stage.operations)
                        for stage in point.stages
                        if isinstance(stage, ComputeStage)
                    ),
                    "compute_node_ids": [
                        operation.kernel_id
                        for stage in point.stages
                        if isinstance(stage, ComputeStage)
                        for operation in stage.operations
                    ],
                    "route_count": sum(
                        len(operation.command.requests)
                        for stage in point.stages
                        if isinstance(stage, CollectStage)
                        for operation in stage.operations
                    ),
                    "state_resource_count": sum(
                        len(stage.operations)
                        for stage in point.stages
                        if isinstance(stage, ApplyStateStage)
                    ),
                    "stage_count": len(point.stages),
                },
            ),
        )
        self._append(point_entry)
        for stage in point.stages:
            if isinstance(stage, ComputeStage):
                self._execute_compute_stage(frame, stage)
            elif isinstance(stage, ApplyStateStage):
                self._execute_apply_stage(frame, stage)
            else:
                self._execute_collect_stage(frame, stage)
            if has_blocking_problems(self.problems[problem_count_before:]):
                break

        if not has_blocking_problems(self.problems[problem_count_before:]):
            self._validate_point_outputs(frame)
        if frame.observables and not has_blocking_problems(
            self.problems[problem_count_before:]
        ):
            self._commit_point_measurement(frame)
        point_failed = has_blocking_problems(self.problems[problem_count_before:])
        self.point_results.append(
            PointExecutionResult(
                point_index=point.point_index,
                point_uid=point.point_uid,
                result="failed" if point_failed else "succeeded",
                stats=frame.stats.freeze(point_index=point.point_index),
            )
        )
        self._append(
            point_entry.model_copy(
                update={"state": "failed" if point_failed else "completed"}
            )
        )

    def _execute_compute_stage(
        self,
        frame: _PointFrame,
        stage: ComputeStage,
    ) -> None:
        for operation in stage.operations:
            entry = self._entry(
                operation_id=operation.operation_id,
                stage=stage.kind,
                effect="pure",
                state="started",
                point_index=frame.point.point_index,
                evidence={
                    "kernel_id": operation.kernel_id,
                    **_dependency_summary(operation.dependencies),
                },
            )
            self._append(entry)
            try:
                inputs = {
                    name: (
                        value.value
                        if isinstance(value, BoundInput)
                        else frame.compute_results[value.operation_id]
                    )
                    for name, value in operation.inputs.items()
                }
                raw_result, reused = self._invoke_compute(operation, inputs)
                result = _unwrap_payload_values(
                    coerce_literal(
                        operation.output_type,
                        raw_result,
                        path=("operations", operation.operation_id, "output"),
                    )
                )
                committed_payload: CommittedPayloadEvidence | None = None
                if operation.payload_slot is not None:
                    fingerprint = content_fingerprint(result)
                    content_hash = stable_content_hash(fingerprint)
                    committed_payload = self.payload_evidence_committer.commit(
                        PayloadEvidence(
                            run_id=self.run_id,
                            operation_id=operation.operation_id,
                            point_index=frame.point.point_index,
                            payload_id=operation.payload_slot.id,
                            schema_id=operation.payload_slot.schema_id,
                            content_hash=content_hash,
                            fingerprint=fingerprint,
                        )
                    )
                else:
                    content_hash = None
            except Exception as error:
                problem = self._problem_from_exception(
                    "compute_operation_failed",
                    f"compute operation {operation.operation_id} failed",
                    error,
                    operation_id=operation.operation_id,
                    point_index=frame.point.point_index,
                )
                self.problems.append(problem)
                self._append(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                return
            frame.compute_results[operation.operation_id] = result
            if reused:
                frame.stats.compute_reused_node_count += 1
            else:
                frame.stats.compute_evaluated_node_count += 1
            if operation.payload_slot is not None:
                slot = operation.payload_slot
                frame.payloads[slot.id] = CommandPayload(
                    id=slot.id,
                    schema_id=slot.schema_id,
                    evidence_ref=committed_payload.ref
                    if committed_payload is not None
                    else None,
                    content_hash=content_hash,
                    metadata={
                        "operation_id": operation.operation_id,
                        "kernel_id": operation.kernel_id,
                        "point_index": frame.point.point_index,
                        "compute_status": "reused" if reused else "evaluated",
                    },
                    payload=result,
                )
                frame.stats.compute_payload_count += 1
                self._observe_payload(frame.payloads[slot.id])
            self._append(
                entry.model_copy(
                    update={
                        "state": "completed",
                        "evidence": {
                            "kernel_id": operation.kernel_id,
                            **_dependency_summary(operation.dependencies),
                            "compute_status": "reused" if reused else "evaluated",
                            **(
                                {
                                    "payload_id": operation.payload_slot.id,
                                    "schema_id": operation.payload_slot.schema_id,
                                    "content_hash": content_hash,
                                    "payload_ref": (
                                        committed_payload.ref
                                        if committed_payload is not None
                                        else None
                                    ),
                                    **payload_summary(result),
                                }
                                if operation.payload_slot is not None
                                else {}
                            ),
                        },
                    }
                )
            )

    def _invoke_compute(
        self,
        operation: ComputeOperation,
        inputs: dict[str, object],
    ) -> tuple[object, bool]:
        if operation.cache_namespace is None:
            return operation.kernel(**inputs), False
        selected_key = (
            operation.cache_key
            if operation.cache_key is not None
            else tuple(
                (name, _versioned_value(value))
                for name, value in sorted(inputs.items())
            )
        )
        key = (operation.cache_namespace, _versioned_value(selected_key))
        if key in self._compute_cache:
            return self._compute_cache[key], True
        result = operation.kernel(**inputs)
        self._compute_cache[key] = result
        return result, False

    def _execute_apply_stage(
        self,
        frame: _PointFrame,
        stage: ApplyStateStage,
    ) -> None:
        for operation in stage.operations:
            if not self._apply_state_operation(frame, operation, stage=stage.kind):
                return

    def _apply_state_operation(
        self,
        frame: _PointFrame,
        operation: ApplyStateOperation,
        *,
        stage: ExecutionStage,
    ) -> bool:
        current = self.current_states.get(operation.instrument_id)
        if current is None:
            self.problems.append(
                self._problem(
                    "missing_current_state",
                    f"missing current state for {operation.instrument_id}",
                    operation_id=operation.operation_id,
                    point_index=frame.point.point_index,
                    instrument_id=operation.instrument_id,
                )
            )
            return False
        fields, skipped_count = _changed_state_fields(operation, current=current)
        frame.stats.skipped_field_count += skipped_count
        entry = self._entry(
            operation_id=operation.operation_id,
            stage=stage,
            effect="state_write",
            state="started",
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "field_count": len(fields),
                "skipped_field_count": skipped_count,
            },
        )
        if not fields:
            self._append(
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
        description = self.descriptions.get(operation.instrument_id)
        if description is not None:
            command_problems = contextualize_problems(
                validate_state_command(
                    command=command,
                    description=description,
                    payloads=frame.payloads,
                ),
                run_id=self.run_id,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.extend(command_problems)
            if has_blocking_problems(command_problems):
                self._append(
                    entry.model_copy(
                        update={
                            "state": "failed",
                            "problems": command_problems,
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
                return False
        # The durable intent must exist before the driver sees the command.
        self._append(entry)
        driver = self.drivers[operation.instrument_id]
        receipt_evidence: dict[str, JsonValue] = {}
        try:
            receipt = _normalize_apply_receipt(driver.apply_state(command))
            receipt_evidence = _receipt_evidence(receipt)
            return self._complete_apply_receipt(
                frame=frame,
                operation=operation,
                entry=entry,
                current=current,
                fields=fields,
                command=command,
                receipt=receipt,
                receipt_evidence=receipt_evidence,
            )
        except Exception as error:
            self._indeterminate = True
            problem = self._problem_from_exception(
                "instrument_apply_unknown",
                f"instrument apply outcome is unknown for {operation.instrument_id}",
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._append_transition_best_effort(
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
        except BaseException as error:
            self._indeterminate = True
            problem = self._record_interruption(
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self._append_transition_best_effort(
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

    def _complete_apply_receipt(
        self,
        *,
        frame: _PointFrame,
        operation: ApplyStateOperation,
        entry: ExecutionTransition,
        current: InstrumentStateSnapshot,
        fields: list[InstrumentStateCommandField],
        command: InstrumentStateCommand,
        receipt: ApplyReceipt,
        receipt_evidence: dict[str, JsonValue],
    ) -> bool:
        receipt_problems = contextualize_problems(
            receipt.problems,
            run_id=self.run_id,
            operation_id=operation.operation_id,
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
        )
        self.problems.extend(receipt_problems)
        receipt_failed = has_blocking_problems(receipt_problems)
        if receipt.status == "applied" and receipt_failed:
            self._indeterminate = True
            problem = self._problem(
                "instrument_apply_receipt_conflict",
                (
                    f"instrument {operation.instrument_id} reported applied "
                    "together with blocking problems"
                ),
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "problems": (*receipt_problems, problem),
                        "evidence": {
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
                    }
                )
            )
            # A contradictory receipt cannot safely advance predicted state.
            return False
        if receipt.status != "applied":
            if receipt.status == "unknown":
                self._indeterminate = True
            if not receipt_failed:
                problem = self._problem(
                    "instrument_state_not_applied",
                    (
                        f"instrument {operation.instrument_id} reported "
                        f"{receipt.status!r} for state operation"
                    ),
                    operation_id=operation.operation_id,
                    point_index=frame.point.point_index,
                    instrument_id=operation.instrument_id,
                )
                self.problems.append(problem)
                operation_problems = (*receipt_problems, problem)
            else:
                operation_problems = receipt_problems
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": (
                            "unknown" if receipt.status == "unknown" else "failed"
                        ),
                        "problems": operation_problems,
                        "evidence": {
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
                    }
                )
            )
            # Never advance predicted state or continue to another resource.
            return False
        next_state = receipt.state or apply_state_command_to_snapshot(current, command)
        if next_state.instrument_id != operation.instrument_id:
            problem = self._problem(
                "instrument_apply_state_mismatch",
                "apply receipt state belongs to a different instrument",
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._indeterminate = True
            self._append_after_effect(
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
        frame.stats.changed_field_count += len(fields)
        frame.stats.state_command_count += 1
        frame.stats.state_payload_count += len(command.payloads)
        self._append_after_effect(
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
        frame: _PointFrame,
        base: Mapping[str, object],
        *,
        changed_field_count: int,
        state_command_count: int,
        payload_count: int,
    ) -> dict[str, object]:
        return {
            **base,
            "compute_evaluated_node_count": (frame.stats.compute_evaluated_node_count),
            "compute_reused_node_count": frame.stats.compute_reused_node_count,
            "compute_payload_count": frame.stats.compute_payload_count,
            "changed_field_count": changed_field_count,
            "skipped_field_count": base.get("skipped_field_count", 0),
            "state_command_count": state_command_count,
            "payload_count": payload_count,
        }

    def _execute_collect_stage(
        self,
        frame: _PointFrame,
        stage: CollectStage,
    ) -> None:
        for operation in stage.operations:
            if not self._collect_operation(frame, operation, stage=stage.kind):
                return

    def _collect_operation(
        self,
        frame: _PointFrame,
        operation: CollectOperation,
        *,
        stage: ExecutionStage,
    ) -> bool:
        command = operation.command.model_copy(
            update={"operation_id": operation.operation_id, "attempt": 1}
        )
        entry = self._entry(
            operation_id=operation.operation_id,
            stage=stage,
            effect="acquisition",
            state="started",
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "request_count": len(operation.command.requests),
                "product_ids": [item.id for item in operation.command.requests],
                **_command_evidence(command),
            },
        )
        self._append(entry)
        try:
            receipt = _normalize_collect_receipt(
                self.drivers[operation.instrument_id].collect(command)
            )
        except Exception as error:
            self._indeterminate = True
            problem = self._problem_from_exception(
                "instrument_collect_unknown",
                "instrument collection outcome is unknown for "
                f"{operation.instrument_id}",
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "unknown", "problems": (problem,)})
            )
            return False
        except BaseException as error:
            self._indeterminate = True
            problem = self._record_interruption(
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "unknown", "problems": (problem,)})
            )
            return False
        receipt_problems = contextualize_problems(
            receipt.problems,
            run_id=self.run_id,
            operation_id=operation.operation_id,
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
        )
        self.problems.extend(receipt_problems)
        receipt_evidence = _receipt_evidence(receipt)
        if receipt.status != "collected":
            if receipt.status == "unknown":
                self._indeterminate = True
            if not has_blocking_problems(receipt_problems):
                problem = self._problem(
                    "instrument_collection_not_completed",
                    f"instrument {operation.instrument_id} reported {receipt.status!r}",
                    operation_id=operation.operation_id,
                    point_index=frame.point.point_index,
                    instrument_id=operation.instrument_id,
                )
                self.problems.append(problem)
                operation_problems = (*receipt_problems, problem)
            else:
                operation_problems = receipt_problems
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": (
                            "unknown" if receipt.status == "unknown" else "failed"
                        ),
                        "problems": operation_problems,
                        "evidence": {**entry.evidence, **receipt_evidence},
                    }
                )
            )
            return False
        assert receipt.readback is not None
        readback = receipt.readback
        try:
            chunk = CollectionChunk(
                run_id=self.run_id,
                operation_id=operation.operation_id,
                attempt=command.attempt,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
                readback=readback,
            )
            committed = self.collection_committer.commit(chunk)
        except Exception as error:
            self._indeterminate = True
            problem = self._problem_from_exception(
                "collection_readback_commit_failed",
                "collection completed but its readback could not be committed",
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
            self.problems.append(problem)
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "unknown", "problems": (problem,)})
            )
            return False
        except BaseException as error:
            self._indeterminate = True
            problem = self._record_interruption(
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "unknown", "problems": (problem,)})
            )
            return False
        validation_problems = contextualize_problems(
            _validate_readback(operation, readback),
            run_id=self.run_id,
            operation_id=operation.operation_id,
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
        )
        operation_problems = (*receipt_problems, *validation_problems)
        self.problems.extend(validation_problems)
        if not has_blocking_problems(operation_problems):
            self._merge_readback(frame, operation, readback)
        failed = has_blocking_problems(operation_problems)
        self._append_after_effect(
            entry.model_copy(
                update={
                    "state": "failed" if failed else "completed",
                    "problems": operation_problems,
                    "evidence": {
                        **entry.evidence,
                        **receipt_evidence,
                        "value_count": len(readback.values),
                        "readback_ref": committed.ref,
                        "readback_content_hash": committed.content_hash,
                    },
                }
            )
        )
        return not failed

    def _merge_readback(
        self,
        frame: _PointFrame,
        operation: CollectOperation,
        readback: InstrumentReadback,
    ) -> None:
        if readback.values:
            frame.instrument_ids.append(operation.instrument_id)
        for product_id, value in readback.values.items():
            output_id = operation.record_bindings.get(product_id)
            if output_id is None:
                self.problems.append(
                    self._problem(
                        "instrument_unexpected_product",
                        (
                            f"instrument {operation.instrument_id} returned "
                            f"unexpected product {product_id}"
                        ),
                        operation_id=operation.operation_id,
                        point_index=frame.point.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            if output_id in frame.observables:
                self.problems.append(
                    self._problem(
                        "instrument_duplicate_output",
                        f"point received duplicate observable {output_id}",
                        operation_id=operation.operation_id,
                        point_index=frame.point.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            frame.observables[output_id] = value

    def _validate_point_outputs(self, frame: _PointFrame) -> None:
        missing = self.program.expected_output_ids - set(frame.observables)
        for output_id in sorted(missing):
            self.problems.append(
                self._problem(
                    "instrument_missing_output",
                    f"point {frame.point.point_index} is missing observable "
                    f"{output_id}",
                    point_index=frame.point.point_index,
                )
            )

    def _commit_point_measurement(self, frame: _PointFrame) -> None:
        operation_id = f"{frame.point.point_uid}.commit-measurement"
        entry = self._entry(
            operation_id=operation_id,
            stage="commit_point",
            effect="persistence",
            state="started",
            point_index=frame.point.point_index,
            evidence=cast(
                "dict[str, JsonValue]",
                {"observable_ids": sorted(frame.observables)},
            ),
        )
        self._append(entry)
        measurement = MeasurementRecord(
            run_id=self.run_id,
            point_index=frame.point.point_index,
            coordinates=dict(frame.point.coordinates),
            observables=dict(frame.observables),
            metadata={
                "instruments": cast(
                    "JsonValue",
                    sorted(set(frame.instrument_ids)),
                )
            },
        )
        try:
            self.measurement_committer.commit(measurement)
        except Exception as error:
            problem = self._problem_from_exception(
                "measurement_commit_failed",
                f"failed to commit point {frame.point.point_index} measurement",
                error,
                operation_id=operation_id,
                point_index=frame.point.point_index,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
            self.problems.append(problem)
            self._append(
                entry.model_copy(update={"state": "failed", "problems": (problem,)})
            )
            return
        self.committed_measurements.append(measurement)
        frame.stats.acquired_record_count += 1
        self._append(entry.model_copy(update={"state": "completed"}))

    def _read_states(
        self, *, phase: Literal["initial", "terminal"]
    ) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        terminal = phase == "terminal"
        for instrument_id in self.program.resource_order:
            operation_id = f"lifecycle.{phase}-read-state.{instrument_id}"
            transition_stage: ExecutionStage = (
                "terminal_readback" if terminal else "initial_readback"
            )
            entry = self._entry(
                operation_id=operation_id,
                stage=transition_stage,
                effect="read",
                state="started",
                instrument_id=instrument_id,
            )
            if terminal:
                self._append_transition_best_effort(entry)
            else:
                self._append(entry)
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
                if terminal:
                    self._append_transition_best_effort(failed_entry)
                else:
                    self._append_after_effect(failed_entry)
                continue
            except BaseException as error:
                problem = self._record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self._append_transition_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            states.append(state)
            completed_entry = entry.model_copy(update={"state": "completed"})
            if terminal:
                self._append_transition_best_effort(completed_entry)
            else:
                self._append_after_effect(completed_entry)
        return states

    def _finalize_drivers(self) -> None:
        action = "abort" if has_blocking_problems(self.problems) else "cleanup"
        used = set(self.program.resource_order)
        extras = tuple(sorted(set(self.drivers) - used))
        managed_order = (
            *extras,
            *(
                instrument_id
                for instrument_id in self.program.resource_order
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
            self._append_transition_best_effort(entry)

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
                self._append_transition_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            except BaseException as error:
                problem = self._record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self._append_transition_best_effort(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "completed"})
            )

    def _capture_terminal_states(self) -> None:
        try:
            self.final_state = self._read_states(phase="terminal")
        except ExecutionJournalError as error:
            self.problems.append(
                self._problem(
                    "execution_journal_commit_failed",
                    str(error),
                    category=ProblemCategory.STORAGE,
                    phase=ProblemPhase.PERSISTENCE,
                )
            )

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

    def _append(self, entry: ExecutionTransition) -> None:
        self.journal.append(entry)

    def _append_after_effect(self, entry: ExecutionTransition) -> None:
        try:
            self.journal.append(entry)
        except Exception:
            self._indeterminate = True
            raise

    def _append_transition_best_effort(self, entry: ExecutionTransition) -> None:
        """Record a transition without allowing evidence failure to block safety."""

        try:
            self.journal.append(entry)
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
                    category=ProblemCategory.STORAGE,
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
        except BaseException as error:
            logger.error(
                "execution payload observer failed",
                extra={"run_id": self.run_id, "payload_id": payload.id},
                exc_info=(type(error), error, error.__traceback__),
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
            category=ProblemCategory.INTERRUPTED,
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
        category: ProblemCategory = ProblemCategory.OPERATION,
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
            category=category,
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
        category: ProblemCategory = ProblemCategory.EXTERNAL_FAILURE,
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
            category=category,
        )

    def _result(self) -> ExecutionEngineResult:
        if self._interruption is not None:
            result: RunResult = "cancelled"
            certainty: RunCertainty = (
                "indeterminate" if self._indeterminate else "known"
            )
            termination_reason = "interrupted"
        elif self._indeterminate:
            result = "failed"
            certainty = "indeterminate"
            termination_reason = "effect_outcome_unknown"
        elif has_blocking_problems(self.problems):
            result = "failed"
            certainty = "known"
            termination_reason = "blocking_problem"
        else:
            result = "succeeded"
            certainty = "known"
            termination_reason = "completed"
        return ExecutionEngineResult(
            run_id=self.run_id,
            experiment_id=self.program.experiment_id,
            result=result,
            certainty=certainty,
            termination_reason=termination_reason,
            problems=tuple(self.problems),
            measurements=tuple(self.committed_measurements),
            initial_state=tuple(self.initial_state),
            final_state=tuple(self.final_state),
            points=tuple(self.point_results),
            interruption=self._interruption,
        )


def _changed_state_fields(
    operation: ApplyStateOperation,
    *,
    current: InstrumentStateSnapshot,
) -> tuple[list[InstrumentStateCommandField], int]:
    current_by_key = {
        (field.capability_id, field.field_path): field.value for field in current.fields
    }
    fields: list[InstrumentStateCommandField] = []
    skipped = 0
    for target in operation.targets:
        key = (target.capability_id, target.field_path)
        field = target.command_field(resource_id=operation.instrument_id)
        if not target.channel_bindings and current_by_key.get(key) == target.value:
            skipped += 1
            continue
        fields.append(field)
    return fields, skipped


def _referenced_payloads(
    fields: list[InstrumentStateCommandField],
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


def _validate_readback(
    operation: CollectOperation,
    readback: InstrumentReadback,
) -> list[Problem]:
    problems: list[Problem] = []
    requests = {request.id: request for request in operation.command.requests}
    for product_id in sorted(set(requests) - set(readback.values)):
        problems.append(
            _readback_problem(
                "instrument_missing_product",
                f"instrument {operation.instrument_id} did not return "
                f"requested product {product_id}",
                product_id,
            )
        )
    for product_id in sorted(set(readback.values) - set(requests)):
        problems.append(
            _readback_problem(
                "instrument_unexpected_product",
                f"instrument {operation.instrument_id} returned unexpected "
                f"product {product_id}",
                product_id,
            )
        )
    for product_id in sorted(set(requests) & set(readback.values)):
        request = requests[product_id]
        value = readback.values[product_id]
        actual_dtype = _readback_dtype(value)
        if not _readback_dtype_compatible(request.dtype, value):
            problems.append(
                _readback_problem(
                    "instrument_readback_dtype_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned {actual_dtype}, expected {request.dtype}",
                    product_id,
                    "dtype",
                )
            )
        actual_unit = value.unit
        if request.unit is not None and (
            actual_unit is None or not compatible_units(request.unit, actual_unit)
        ):
            problems.append(
                _readback_problem(
                    "instrument_readback_unit_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned unit {actual_unit!r}, expected "
                    f"{request.unit!r}-compatible units",
                    product_id,
                    "unit",
                )
            )
        expected_shape = [axis.size for axis in request.dimensions]
        actual_shape = value.shape if isinstance(value, MeasurementArray) else []
        if actual_shape != expected_shape:
            problems.append(
                _readback_problem(
                    "instrument_readback_shape_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned shape {actual_shape}, expected {expected_shape}",
                    product_id,
                    "shape",
                )
            )
    return problems


def _readback_dtype(value: MeasurementValue) -> str:
    if isinstance(value, MeasurementArray):
        return value.dtype
    if isinstance(value, ComplexQuantity):
        return "complex128"
    return "float64"


def _readback_dtype_compatible(expected: str, value: MeasurementValue) -> bool:
    actual = _readback_dtype(value)
    if actual == expected:
        return True
    if expected == "float64" and actual == "int64":
        return True
    if expected == "complex128" and actual in {"float64", "int64"}:
        return True
    return (
        expected == "int64"
        and isinstance(value, Quantity)
        and int(value.value) == value.value
    )


def _command_evidence(command: BaseModel) -> dict[str, JsonValue]:
    envelope = command.model_dump(mode="json")
    return {
        "command": envelope,
        "command_content_hash": stable_content_hash(envelope),
    }


def _receipt_evidence(receipt: ApplyReceipt | CollectReceipt) -> dict[str, JsonValue]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def _normalize_apply_receipt(value: object) -> ApplyReceipt:
    if not isinstance(value, ApplyReceipt):
        msg = (
            "instrument apply_state must return ApplyReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ApplyReceipt.model_validate(value.model_dump(mode="json"))


def _normalize_collect_receipt(value: object) -> CollectReceipt:
    if not isinstance(value, CollectReceipt):
        msg = (
            "instrument collect must return CollectReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return CollectReceipt.model_validate(value.model_dump(mode="json"))


def _unwrap_payload_values(value: object) -> object:
    if isinstance(value, PayloadValue):
        return value.payload
    if isinstance(value, list):
        return [_unwrap_payload_values(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(
            _unwrap_payload_values(item) for item in cast("tuple[object, ...]", value)
        )
    if isinstance(value, dict):
        return {
            name: _unwrap_payload_values(item)
            for name, item in cast("dict[object, object]", value).items()
        }
    return value


def _versioned_value(value: object) -> object:
    return stable_content_hash(content_fingerprint(value))


def _readback_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("instrument_readback", "values", *path),
    )


__all__ = [
    "ExecutionEngine",
    "ExecutionEngineResult",
    "ExecutionPointStats",
    "NoopResourceLeaseManager",
    "PointExecutionResult",
    "ResourceLeaseManager",
]
