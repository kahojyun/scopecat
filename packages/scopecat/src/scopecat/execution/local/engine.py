"""Small synchronous interpreter for :mod:`scopecat.execution.local.program`."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import BaseModel, JsonValue

from scopecat.compiler.semantic.model import ValueId
from scopecat.execution.events import RuntimeTransitionProjector, payload_summary
from scopecat.execution.local.program import (
    ActionStage,
    ApplyStateOperation,
    ApplyStateStage,
    BoundInput,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeStage,
    ExecutionProgram,
    InstrumentActionOperation,
    PointProgram,
)
from scopecat.execution.ports.journal import (
    CollectionRepository,
    ExecutionJournal,
    ExecutionJournalError,
    PayloadEvidenceCommitter,
)
from scopecat.execution.ports.measurement import MeasurementRecordCommitter
from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat.execution.resources import NoopResourceLeaseManager
from scopecat.kernel.content_identity import (
    content_fingerprint,
    model_wire_content_hash,
    stable_content_hash,
)
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import (
    LocationPathItem,
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.value_validation import coerce_literal
from scopecat.measurements.contracts import (
    MeasurementValueContractIssueCode,
    measurement_value_contract_issues,
)
from scopecat.measurements.results import MeasurementRecord, MeasurementValue
from scopecat.records.artifact import CommandPayload
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionEffect,
    ExecutionStage,
    ExecutionTransition,
    JournalEntryState,
    PayloadEvidence,
)
from scopecat.records.instrument import (
    CommandChannelBinding,
    InstrumentReadback,
    InstrumentStateSnapshot,
)
from scopecat.records.measurement_recording import (
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
)
from scopecat.records.run import RunCertainty, RunResult, RunStatus
from scopecat.sdk.instruments.contracts import (
    ActionReceipt,
    ApplyReceipt,
    CollectReceipt,
    InstrumentActionCommand,
    InstrumentActionCommandField,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    apply_state_command_to_snapshot,
    validate_action_command,
    validate_state_command,
)

logger = logging.getLogger(__name__)

_RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"


class CapturedMiddleEffectFailure(Exception):
    """Stop a segment loop after the caller retained its structured failure."""


@dataclass(frozen=True, slots=True)
class ExecutionPointStats:
    point_index: int
    changed_field_count: int = 0
    skipped_field_count: int = 0
    state_command_count: int = 0
    state_payload_count: int = 0
    action_command_count: int = 0
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
    def action_command_count(self) -> int:
        return sum(point.stats.action_command_count for point in self.points)

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
    action_command_count: int = 0
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
            action_command_count=self.action_command_count,
            compute_evaluated_node_count=self.compute_evaluated_node_count,
            compute_reused_node_count=self.compute_reused_node_count,
            compute_payload_count=self.compute_payload_count,
            acquired_record_count=self.acquired_record_count,
        )


@dataclass(slots=True)
class _PointFrame:
    point: PointProgram
    stats: _MutablePointStats = field(default_factory=_MutablePointStats)
    compute_results: dict[ValueId, object] = field(default_factory=dict)
    payloads: dict[str, CommandPayload] = field(default_factory=dict)
    product_values: dict[ProductUseId, MeasurementValue] = field(default_factory=dict)
    observables: dict[str, MeasurementValue] = field(default_factory=dict)
    instrument_ids: list[str] = field(default_factory=list)


class ExecutionEngine:
    """Interpret one closed program with fail-closed effect journaling.

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
        measurements: MeasurementRecordCommitter,
        readbacks: CollectionRepository,
        payloads: PayloadEvidenceCommitter,
        descriptions: Mapping[str, InstrumentDescription] | None = None,
        resources: ResourceLeaseManager | None = None,
        transition_observer: RuntimeTransitionProjector | None = None,
        payload_observer: Callable[[CommandPayload], None] | None = None,
    ) -> None:
        self.run_id = run_id
        self.program = program
        self.drivers = dict(drivers)
        self.journal = journal
        self.measurement_committer = measurements
        self.measurement_recording_contract_fingerprint = (
            _measurement_recording_contract_fingerprint(program)
        )
        self.collection_repository = readbacks
        self.payload_evidence_committer = payloads
        self.descriptions = dict(descriptions or {})
        self.resources = resources or NoopResourceLeaseManager()
        self.transition_observer = transition_observer
        self.payload_observer = payload_observer
        self.problems: list[Problem] = []
        self.initial_state: list[InstrumentStateSnapshot] = []
        self.final_state: list[InstrumentStateSnapshot] = []
        self.current_states: dict[str, InstrumentStateSnapshot] = {}
        self.point_results: list[PointExecutionResult] = []
        self.committed_measurements: list[MeasurementRecord] = []
        self._compute_cache: dict[tuple[str, str, object], object] = {}
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

    def run_around_point_segments(
        self,
        segments: Sequence[tuple[tuple[int, ...], Callable[[], None]]],
    ) -> ExecutionEngineResult:
        """Execute ordered domain effects between local state and collection.

        Planning has already partitioned the canonical point order so desired
        local state is invariant inside each segment. Drivers stay provisioned
        for the complete run; each segment reconciles its first point's state,
        invokes its domain effect, then performs point-local collection.
        """

        selected_segments = tuple(segments)
        covered_indices: list[int] = []
        for point_indices, middle in selected_segments:
            if not point_indices:
                msg = "point segments must contain at least one point"
                raise ValueError(msg)
            if not callable(middle):
                msg = "point-segment middle effects must be callable"
                raise TypeError(msg)
            if tuple(point_indices) != tuple(
                range(point_indices[0], point_indices[0] + len(point_indices))
            ):
                msg = "point segments must contain contiguous ordered indices"
                raise ValueError(msg)
            covered_indices.extend(point_indices)
        if covered_indices != list(range(len(self.program.points))):
            msg = "point segments must exactly partition the execution program"
            raise ValueError(msg)
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
                    for point_indices, middle in selected_segments:
                        if has_blocking_problems(self.problems):
                            break
                        segment_points = tuple(
                            self.program.points[index] for index in point_indices
                        )
                        hoisted_stats = self._execute_point_state(segment_points[0])
                        if has_blocking_problems(self.problems):
                            break
                        middle()
                        if has_blocking_problems(self.problems):
                            break
                        for point_offset, point in enumerate(segment_points):
                            collection_point = PointProgram(
                                point_index=point.point_index,
                                point_uid=point.point_uid,
                                coordinates=point.coordinates,
                                stages=tuple(
                                    stage
                                    for stage in point.stages
                                    if isinstance(stage, CollectStage)
                                ),
                            )
                            self._execute_point(
                                collection_point,
                                initial_stats=(
                                    hoisted_stats if point_offset == 0 else None
                                ),
                            )
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
                except CapturedMiddleEffectFailure:
                    pass
                except Exception as error:
                    self.problems.append(
                        self._problem_from_exception(
                            "execution_middle_effect_failed",
                            "execution point-set effect failed",
                            error,
                        )
                    )
                except BaseException as error:
                    self._record_interruption(error)
                finally:
                    self._finalize_drivers()
                    finalized = True
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

    def _execute_point_state(self, point: PointProgram) -> _MutablePointStats:
        frame = _PointFrame(point=point)
        for stage in point.stages:
            if not isinstance(stage, ApplyStateStage):
                continue
            self._execute_apply_stage(frame, stage)
            if has_blocking_problems(self.problems):
                return frame.stats
        return frame.stats

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

    def _execute_point(
        self,
        point: PointProgram,
        *,
        initial_stats: _MutablePointStats | None = None,
    ) -> None:
        frame = _PointFrame(
            point=point,
            stats=_MutablePointStats() if initial_stats is None else initial_stats,
        )
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
                    "compute_operation_ids": [
                        operation.semantic_operation_id
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
                    "action_count": sum(
                        len(stage.operations)
                        for stage in point.stages
                        if isinstance(stage, ActionStage)
                    ),
                    "stage_count": len(point.stages),
                },
            ),
        )
        self._observe_transition(point_entry)
        for stage in point.stages:
            if isinstance(stage, ComputeStage):
                self._execute_compute_stage(frame, stage)
            elif isinstance(stage, ApplyStateStage):
                self._execute_apply_stage(frame, stage)
            elif isinstance(stage, ActionStage):
                self._execute_action_stage(frame, stage)
            else:
                self._execute_collect_stage(frame, stage)
            if has_blocking_problems(self.problems[problem_count_before:]):
                break

        if not has_blocking_problems(self.problems[problem_count_before:]):
            self._validate_point_outputs(frame)
        if frame.observables and not has_blocking_problems(
            self.problems[problem_count_before:]
        ):
            self._record_point_measurement(frame)
        point_failed = has_blocking_problems(self.problems[problem_count_before:])
        self.point_results.append(
            PointExecutionResult(
                point_index=point.point_index,
                point_uid=point.point_uid,
                result="failed" if point_failed else "succeeded",
                stats=frame.stats.freeze(point_index=point.point_index),
            )
        )
        self._observe_transition(
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
                    "semantic_operation_id": operation.semantic_operation_id,
                    "implementation_id": operation.implementation_id,
                    **_dependency_summary(operation.dependencies),
                },
            )
            self._observe_transition(entry)
            try:
                inputs = {
                    name: (
                        value.value
                        if isinstance(value, BoundInput)
                        else frame.compute_results[value.value_id]
                    )
                    for name, value in operation.inputs.items()
                }
                raw_result, reused = self._invoke_compute(operation, inputs)
                result = _unwrap_payload_values(
                    coerce_literal(
                        operation.result.value_type,
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
                self._observe_transition(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                return
            frame.compute_results[operation.result.id] = result
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
                    operation_id=operation.operation_id,
                    semantic_operation_id=operation.semantic_operation_id,
                    implementation_id=operation.implementation_id,
                    point_index=frame.point.point_index,
                    compute_status="reused" if reused else "evaluated",
                    payload=result,
                )
                frame.stats.compute_payload_count += 1
                self._observe_payload(frame.payloads[slot.id])
            self._observe_transition(
                entry.model_copy(
                    update={
                        "state": "completed",
                        "evidence": {
                            "semantic_operation_id": operation.semantic_operation_id,
                            "implementation_id": operation.implementation_id,
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
        key = (
            operation.implementation_id,
            operation.cache_namespace,
            _versioned_value(selected_key),
        )
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
            self._observe_transition(
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
                self._observe_transition(
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
        self._commit_transition(entry)
        driver = self.drivers[operation.instrument_id]
        receipt_evidence: dict[str, JsonValue] = {}
        try:
            receipt = _normalize_apply_receipt(driver.apply_state(command))
            receipt_evidence = _apply_receipt_evidence(receipt)
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
            self._commit_transition_best_effort(
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
            self._commit_transition_best_effort(
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
            self._commit_after_effect(
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
            self._commit_after_effect(
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
        frame.stats.changed_field_count += len(fields)
        frame.stats.state_command_count += 1
        frame.stats.state_payload_count += len(command.payloads)
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

    def _execute_action_stage(
        self,
        frame: _PointFrame,
        stage: ActionStage,
    ) -> None:
        for operation in stage.operations:
            if not self._execute_action(frame, operation, stage=stage.kind):
                return

    def _execute_action(
        self,
        frame: _PointFrame,
        operation: InstrumentActionOperation,
        *,
        stage: ExecutionStage,
    ) -> bool:
        fields = [field.command_field() for field in operation.fields]
        command = InstrumentActionCommand(
            operation_id=operation.operation_id,
            instrument_id=operation.instrument_id,
            capability_id=operation.capability_id,
            fields=fields,
            payloads=_referenced_payloads(fields, frame.payloads),
        )
        entry = self._entry(
            operation_id=operation.operation_id,
            stage=stage,
            effect="action",
            state="started",
            point_index=frame.point.point_index,
            instrument_id=operation.instrument_id,
            evidence={
                "capability_id": operation.capability_id,
                "field_count": len(fields),
                **_command_evidence(command),
            },
        )
        description = self.descriptions.get(operation.instrument_id)
        if description is not None:
            command_problems = contextualize_problems(
                validate_action_command(
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
                self._observe_transition(
                    entry.model_copy(
                        update={"state": "failed", "problems": command_problems}
                    )
                )
                return False

        # One-shot intent must be durable before the driver can perform it.
        self._commit_transition(entry)
        frame.stats.action_command_count += 1
        receipt_evidence: dict[str, JsonValue] = {}
        try:
            receipt = _normalize_action_receipt(
                self.drivers[operation.instrument_id].action(command)
            )
            receipt_evidence = _action_receipt_evidence(receipt)
        except Exception as error:
            self._indeterminate = True
            problem = self._problem_from_exception(
                "instrument_action_unknown",
                f"instrument action outcome is unknown for {operation.instrument_id}",
                error,
                operation_id=operation.operation_id,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
            )
            self.problems.append(problem)
            self._commit_transition_best_effort(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "problems": (problem,),
                        "evidence": {**entry.evidence, **receipt_evidence},
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
            self._commit_transition_best_effort(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "problems": (problem,),
                        "evidence": {**entry.evidence, **receipt_evidence},
                    }
                )
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
        if receipt.status != "performed":
            if receipt.status == "unknown":
                self._indeterminate = True
            self._commit_after_effect(
                entry.model_copy(
                    update={
                        "state": (
                            "unknown" if receipt.status == "unknown" else "failed"
                        ),
                        "problems": receipt_problems,
                        "evidence": {**entry.evidence, **receipt_evidence},
                    }
                )
            )
            return False
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "completed",
                    "problems": receipt_problems,
                    "evidence": {**entry.evidence, **receipt_evidence},
                }
            )
        )
        return True

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
        command = operation.command.model_copy(update={"attempt": 1}, deep=True)
        command_evidence = _command_evidence(command)
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
                **command_evidence,
            },
        )
        self._commit_transition(entry)
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
            self._commit_transition_best_effort(
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
            self._commit_transition_best_effort(
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
        receipt_evidence = _collect_receipt_evidence(receipt)
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
            self._commit_after_effect(
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
                command_content_hash=cast(
                    "str",
                    command_evidence["command_content_hash"],
                ),
                attempt=command.attempt,
                point_index=frame.point.point_index,
                instrument_id=operation.instrument_id,
                readback=readback,
            )
            chunk_receipt = _validate_collection_chunk_receipt(
                self.collection_repository.commit(chunk),
                chunk=chunk,
            )
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
            self._commit_transition_best_effort(
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
            self._commit_transition_best_effort(
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
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "failed" if failed else "completed",
                    "problems": operation_problems,
                    "evidence": {
                        **entry.evidence,
                        **receipt_evidence,
                        "value_count": len(readback.values),
                        "readback_ref": chunk_receipt.ref,
                        "readback_content_hash": chunk_receipt.content_hash,
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
                        point_index=frame.point.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            if binding.product_use_id in frame.product_values:
                self.problems.append(
                    self._problem(
                        "instrument_duplicate_product_use",
                        "point received more than one result for logical product use "
                        f"{binding.product_use_id.value}",
                        operation_id=operation.operation_id,
                        point_index=frame.point.point_index,
                        instrument_id=operation.instrument_id,
                    )
                )
                continue
            frame.product_values[binding.product_use_id] = value

    def _validate_point_outputs(self, frame: _PointFrame) -> None:
        for projection in self.program.record_projections:
            value = frame.product_values.get(projection.product_use_id)
            if value is None:
                self.problems.append(
                    self._problem(
                        "instrument_missing_output",
                        f"point {frame.point.point_index} is missing observable "
                        f"{projection.record_id}",
                        point_index=frame.point.point_index,
                    )
                )
                continue
            frame.observables[projection.record_id] = value

    def _record_point_measurement(self, frame: _PointFrame) -> None:
        measurement = MeasurementRecord(
            run_id=self.run_id,
            logical_point_id=frame.point.point_uid,
            point_index=frame.point.point_index,
            instrument_ids=sorted(set(frame.instrument_ids)),
            coordinates=dict(frame.point.coordinates),
            observables=dict(frame.observables),
        )
        chunk = MeasurementRecordChunk(
            run_id=self.run_id,
            dataset_id=_RAW_MEASUREMENTS_DATASET_ID,
            recording_contract_fingerprint=(
                self.measurement_recording_contract_fingerprint
            ),
            logical_point_id=frame.point.point_uid,
            point_index=frame.point.point_index,
            record=measurement,
        )
        measurement = chunk.record
        operation_id = chunk.operation_id
        entry = self._entry(
            operation_id=operation_id,
            stage="record_measurement",
            effect="persistence",
            state="started",
            point_index=frame.point.point_index,
            evidence=cast(
                "dict[str, JsonValue]",
                {
                    "dataset_id": chunk.dataset_id,
                    "logical_point_id": chunk.logical_point_id,
                    "recording_contract_fingerprint": (
                        chunk.recording_contract_fingerprint
                    ),
                    "chunk_content_hash": chunk.content_hash,
                    "observable_ids": sorted(frame.observables),
                },
            ),
        )
        self._commit_recording_transition(entry)
        try:
            receipt = _validate_measurement_record_receipt(
                self.measurement_committer.commit(chunk),
                chunk=chunk,
            )
        except Exception as error:
            self._indeterminate = True
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
            self._commit_transition_best_effort(
                entry.model_copy(update={"state": "unknown", "problems": (problem,)})
            )
            return
        except BaseException:
            self._indeterminate = True
            self._commit_transition_best_effort(
                entry.model_copy(update={"state": "unknown"})
            )
            raise
        self.committed_measurements.append(measurement)
        frame.stats.acquired_record_count += 1
        self._commit_after_effect(
            entry.model_copy(
                update={
                    "state": "completed",
                    "evidence": {
                        **entry.evidence,
                        "record_ref": receipt.record_ref,
                        "receipt_content_hash": receipt.content_hash,
                    },
                }
            )
        )

    def _read_states(
        self, *, phase: Literal["initial", "terminal"]
    ) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        for instrument_id in self.program.resource_order:
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
            self._observe_transition(entry)
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
                self._observe_transition(failed_entry)
                continue
            except BaseException as error:
                problem = self._record_interruption(
                    error,
                    operation_id=operation_id,
                    instrument_id=instrument_id,
                )
                self._observe_transition(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                continue
            states.append(state)
            completed_entry = entry.model_copy(update={"state": "completed"})
            self._observe_transition(completed_entry)
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

    def _observe_transition(self, entry: ExecutionTransition) -> None:
        if self.transition_observer is not None:
            self.transition_observer.observe(entry)

    def _commit_transition(self, entry: ExecutionTransition) -> None:
        committed = self.journal.append(entry)
        self._observe_transition(committed)

    def _commit_recording_transition(self, entry: ExecutionTransition) -> None:
        if entry.stage != "record_measurement":
            msg = "strict measurement journal commits require record_measurement"
            raise ExecutionJournalError(msg)
        expected = entry.model_dump(
            mode="json",
            exclude={"sequence", "timestamp"},
        )
        try:
            committed = self.journal.append(entry)
            if not isinstance(cast("object", committed), ExecutionTransition):
                msg = "execution journal returned no committed measurement transition"
                raise TypeError(msg)
            normalized = ExecutionTransition.model_validate(
                committed.model_dump(mode="json")
            )
            if normalized.sequence is None:
                msg = (
                    "measurement recording requires a journal-assigned durable sequence"
                )
                raise ValueError(msg)
            actual = normalized.model_dump(
                mode="json",
                exclude={"sequence", "timestamp"},
            )
            if actual != expected:
                msg = (
                    "execution journal changed measurement transition "
                    "identity or evidence"
                )
                raise ValueError(msg)
            self._observe_transition(normalized)
        except Exception as error:
            if isinstance(error, ExecutionJournalError):
                raise
            msg = f"failed to commit measurement transition {entry.operation_id}"
            raise ExecutionJournalError(msg) from error

    def _commit_after_effect(self, entry: ExecutionTransition) -> None:
        try:
            if entry.stage == "record_measurement":
                self._commit_recording_transition(entry)
            else:
                self._commit_transition(entry)
        except Exception:
            self._indeterminate = True
            raise

    def _commit_transition_best_effort(self, entry: ExecutionTransition) -> None:
        """Record a transition without allowing evidence failure to block safety."""

        try:
            if entry.stage == "record_measurement":
                self._commit_recording_transition(entry)
            else:
                self._commit_transition(entry)
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
    fields: Sequence[InstrumentStateCommandField | InstrumentActionCommandField],
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
        expected_shape = [axis.size for axis in request.dimensions]
        for issue in measurement_value_contract_issues(
            value,
            expected_dtype=request.dtype,
            expected_unit=request.unit,
            expected_shape=expected_shape,
        ):
            if issue.code is MeasurementValueContractIssueCode.DTYPE_MISMATCH:
                problems.append(
                    _readback_problem(
                        "instrument_readback_dtype_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned {issue.actual}, expected {issue.expected}",
                        product_id,
                        "dtype",
                    )
                )
            elif issue.code is MeasurementValueContractIssueCode.UNIT_MISMATCH:
                problems.append(
                    _readback_problem(
                        "instrument_readback_unit_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned unit {issue.actual!r}, expected "
                        f"{issue.expected!r}-compatible units",
                        product_id,
                        "unit",
                    )
                )
            elif issue.code is MeasurementValueContractIssueCode.SHAPE_MISMATCH:
                actual_shape = list(cast("tuple[int, ...]", issue.actual))
                expected_contract_shape = list(cast("tuple[int, ...]", issue.expected))
                problems.append(
                    _readback_problem(
                        "instrument_readback_shape_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"returned shape {actual_shape}, "
                        f"expected {expected_contract_shape}",
                        product_id,
                        "shape",
                    )
                )
            elif (
                issue.code is MeasurementValueContractIssueCode.ARRAY_STRUCTURE_MISMATCH
            ):
                value_path = ".".join(str(item) for item in issue.path)
                problems.append(
                    _readback_problem(
                        "instrument_readback_shape_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"array {value_path} has structure {issue.actual!r}, "
                        f"expected {issue.expected!r}",
                        product_id,
                        *issue.path,
                    )
                )
            else:
                value_path = ".".join(str(item) for item in issue.path)
                problems.append(
                    _readback_problem(
                        "instrument_readback_value_mismatch",
                        f"instrument {operation.instrument_id} product {product_id} "
                        f"value {value_path} violates {issue.code.value}: expected "
                        f"{issue.expected!r}, got {issue.actual!r}",
                        product_id,
                        *issue.path,
                    )
                )
    return problems


def _command_evidence(command: BaseModel) -> dict[str, JsonValue]:
    envelope = command.model_dump(mode="json")
    return {
        "command": envelope,
        "command_content_hash": stable_content_hash(envelope),
    }


def _apply_receipt_evidence(receipt: ApplyReceipt) -> dict[str, JsonValue]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def _action_receipt_evidence(receipt: ActionReceipt) -> dict[str, JsonValue]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def _collect_receipt_evidence(receipt: CollectReceipt) -> dict[str, JsonValue]:
    if receipt.status == "collected":
        return {
            "receipt_status": receipt.status,
            **({"receipt_metadata": receipt.metadata} if receipt.metadata else {}),
        }
    # An unknown receipt may contain the only surviving readback candidate.
    # Keep it until uncertain collection evidence has its own typed repository.
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": model_wire_content_hash(receipt),
    }


def _validate_collection_chunk_receipt(
    value: object,
    *,
    chunk: CollectionChunk,
) -> CollectionChunkReceipt:
    if not isinstance(value, CollectionChunkReceipt):
        msg = (
            "collection repository must return CollectionChunkReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    receipt = CollectionChunkReceipt.model_validate(value.model_dump(mode="json"))
    if (
        receipt.operation_id != chunk.operation_id
        or receipt.content_hash != chunk.content_hash
    ):
        msg = "collection receipt does not cover its exact committed chunk"
        raise ValueError(msg)
    return receipt


def _validate_measurement_record_receipt(
    value: object,
    *,
    chunk: MeasurementRecordChunk,
) -> MeasurementRecordReceipt:
    if not isinstance(value, MeasurementRecordReceipt):
        msg = (
            "measurement committer must return MeasurementRecordReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    receipt = MeasurementRecordReceipt.model_validate(value.model_dump(mode="json"))
    if (
        receipt.operation_id != chunk.operation_id
        or receipt.chunk_content_hash != chunk.content_hash
    ):
        msg = "measurement record receipt does not cover its exact committed chunk"
        raise ValueError(msg)
    return receipt


def _measurement_recording_contract_fingerprint(
    program: ExecutionProgram,
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.local_measurement_recording_contract.v1",
                "dataset_id": _RAW_MEASUREMENTS_DATASET_ID,
                "experiment_id": program.experiment_id,
                "points": [
                    {
                        "point_index": point.point_index,
                        "logical_point_id": point.point_uid,
                        "coordinates": dict(point.coordinates),
                    }
                    for point in program.points
                ],
                "product_uses": [
                    {
                        "product_use_id": use.id.value,
                        "product_id": use.product_id.qualified_name,
                    }
                    for use in program.product_uses
                ],
                "record_projections": [
                    {
                        "record_id": projection.record_id,
                        "product_use_id": projection.product_use_id.value,
                        "product_id": projection.product_id.qualified_name,
                    }
                    for projection in program.record_projections
                ],
                "expected_dataset_schema": program.expected_dataset_schema,
            }
        )
    )


def _normalize_apply_receipt(value: object) -> ApplyReceipt:
    if not isinstance(value, ApplyReceipt):
        msg = (
            "instrument apply_state must return ApplyReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ApplyReceipt.model_validate(value.model_dump(mode="json"))


def _normalize_action_receipt(value: object) -> ActionReceipt:
    if not isinstance(value, ActionReceipt):
        msg = (
            "instrument action must return ActionReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ActionReceipt.model_validate(value.model_dump(mode="json"))


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
    "CapturedMiddleEffectFailure",
    "ExecutionEngine",
    "ExecutionEngineResult",
    "ExecutionPointStats",
    "NoopResourceLeaseManager",
    "PointExecutionResult",
    "ResourceLeaseManager",
]
