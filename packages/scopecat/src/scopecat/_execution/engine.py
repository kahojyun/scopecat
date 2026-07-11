"""Small synchronous interpreter for :mod:`scopecat._execution.program`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from pydantic import BaseModel, JsonValue

from scopecat._content_identity import content_fingerprint, stable_content_hash
from scopecat._execution.events import payload_summary
from scopecat._execution.journal import (
    CollectionChunk,
    CollectionCommitter,
    CommittedPayloadEvidence,
    ExecutionEffect,
    ExecutionJournal,
    ExecutionJournalEntry,
    ExecutionJournalError,
    JournalEntryState,
    MeasurementCommitter,
    PayloadEvidence,
    PayloadEvidenceCommitter,
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
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import (
    ApplyReceipt,
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
from scopecat.models.state import PayloadRef
from scopecat.models.value import PayloadValue
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.results import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementRecord,
    MeasurementValue,
)
from scopecat.units import compatible_units
from scopecat.value_validation import coerce_literal


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
    status: str
    stats: ExecutionPointStats


@dataclass(frozen=True, slots=True)
class ExecutionEngineResult:
    """Complete in-memory result; durable evidence is committed incrementally."""

    run_id: str
    experiment_id: str
    status: str
    diagnostics: tuple[Diagnostic, ...]
    measurements: tuple[MeasurementRecord, ...]
    initial_state: tuple[InstrumentStateSnapshot, ...]
    final_state: tuple[InstrumentStateSnapshot, ...]
    points: tuple[PointExecutionResult, ...]
    uncertain: bool = False
    interruption: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    @property
    def success(self) -> bool:
        return self.status == "completed"

    @property
    def completed_point_count(self) -> int:
        return sum(point.status == "completed" for point in self.points)

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
        self.diagnostics: list[Diagnostic] = []
        self.initial_state: list[InstrumentStateSnapshot] = []
        self.final_state: list[InstrumentStateSnapshot] = []
        self.current_states: dict[str, InstrumentStateSnapshot] = {}
        self.point_results: list[PointExecutionResult] = []
        self.committed_measurements: list[MeasurementRecord] = []
        self._compute_cache: dict[tuple[str, object], object] = {}
        self._uncertain = False
        self._interruption: BaseException | None = None

    def run(self) -> ExecutionEngineResult:
        self._validate_drivers()
        if has_blocking_diagnostics(self.diagnostics):
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
                    if not has_blocking_diagnostics(self.diagnostics):
                        for point in self.program.points:
                            self._execute_point(point)
                            if has_blocking_diagnostics(self.diagnostics):
                                break
                except ExecutionJournalError as error:
                    self.diagnostics.append(
                        _diagnostic(
                            "execution_journal_commit_failed",
                            str(error),
                            "execution.journal",
                        )
                    )
                except Exception as error:  # Defensive engine boundary.
                    self.diagnostics.append(
                        _exception_diagnostic(
                            "execution_engine_failed",
                            "execution engine failed",
                            "execution",
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
            self.diagnostics.append(
                _exception_diagnostic(
                    "resource_lease_failed",
                    "failed to acquire or release execution resources",
                    "execution.resources",
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
            self.diagnostics.append(
                _diagnostic(
                    "missing_instrument",
                    f"no instrument provided for resource {instrument_id}",
                    f"resources.{instrument_id}",
                )
            )

    def _execute_point(self, point: PointProgram) -> None:
        frame = _PointFrame(point=point)
        diagnostic_count_before = len(self.diagnostics)
        point_entry = self._entry(
            operation_id=f"{point.point_uid}.point",
            stage="point",
            effect="pure",
            state="started",
            point_index=point.point_index,
            summary={
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
        )
        self._append(point_entry)
        for stage in point.stages:
            if isinstance(stage, ComputeStage):
                self._execute_compute_stage(frame, stage)
            elif isinstance(stage, ApplyStateStage):
                self._execute_apply_stage(frame, stage)
            else:
                self._execute_collect_stage(frame, stage)
            if has_blocking_diagnostics(self.diagnostics[diagnostic_count_before:]):
                break

        if not has_blocking_diagnostics(self.diagnostics[diagnostic_count_before:]):
            self._validate_point_outputs(frame)
        if frame.observables and not has_blocking_diagnostics(
            self.diagnostics[diagnostic_count_before:]
        ):
            self._commit_point_measurement(frame)
        point_failed = has_blocking_diagnostics(
            self.diagnostics[diagnostic_count_before:]
        )
        self.point_results.append(
            PointExecutionResult(
                point_index=point.point_index,
                point_uid=point.point_uid,
                status="failed" if point_failed else "completed",
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
                summary={
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
                        path=f"operations.{operation.operation_id}.output",
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
                diagnostic = _exception_diagnostic(
                    "compute_operation_failed",
                    f"compute operation {operation.operation_id} failed",
                    f"operations.{operation.operation_id}",
                    error,
                )
                self.diagnostics.append(diagnostic)
                self._append(
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    )
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
                        "summary": {
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
        stage: str,
    ) -> bool:
        current = self.current_states.get(operation.instrument_id)
        if current is None:
            self.diagnostics.append(
                _diagnostic(
                    "missing_current_state",
                    f"missing current state for {operation.instrument_id}",
                    operation.instrument_id,
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
            summary={
                "field_count": len(fields),
                "skipped_field_count": skipped_count,
            },
        )
        if not fields:
            self._append(
                entry.model_copy(
                    update={
                        "state": "skipped",
                        "summary": self._state_event_summary(
                            frame,
                            entry.summary,
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
                "summary": {
                    **entry.summary,
                    **_command_evidence(command),
                }
            }
        )
        description = self.descriptions.get(operation.instrument_id)
        if description is not None:
            command_diagnostics = validate_state_command(
                command=command,
                description=description,
                payloads=frame.payloads,
            )
            self.diagnostics.extend(command_diagnostics)
            if has_blocking_diagnostics(command_diagnostics):
                self._append(
                    entry.model_copy(
                        update={
                            "state": "failed",
                            "diagnostics": command_diagnostics,
                            "summary": self._state_event_summary(
                                frame,
                                entry.summary,
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
        receipt_evidence: dict[str, object] = {}
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
            self._uncertain = True
            diagnostic = _exception_diagnostic(
                "instrument_apply_unknown",
                f"instrument apply outcome is unknown for {operation.instrument_id}",
                operation.instrument_id,
                error,
            )
            self.diagnostics.append(diagnostic)
            self._append_transition_best_effort(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "diagnostics": [diagnostic],
                        "summary": {
                            **self._state_event_summary(
                                frame,
                                entry.summary,
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
            self._uncertain = True
            diagnostic = self._record_interruption(
                error,
                path=operation.instrument_id,
            )
            self._append_transition_best_effort(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "diagnostics": [diagnostic],
                        "summary": {
                            **self._state_event_summary(
                                frame,
                                entry.summary,
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
        entry: ExecutionJournalEntry,
        current: InstrumentStateSnapshot,
        fields: list[InstrumentStateCommandField],
        command: InstrumentStateCommand,
        receipt: ApplyReceipt,
        receipt_evidence: dict[str, object],
    ) -> bool:
        self.diagnostics.extend(receipt.diagnostics)
        receipt_failed = has_blocking_diagnostics(receipt.diagnostics)
        if receipt.status == "applied" and receipt_failed:
            self._uncertain = True
            diagnostic = _diagnostic(
                "instrument_apply_receipt_conflict",
                (
                    f"instrument {operation.instrument_id} reported applied "
                    "together with blocking diagnostics"
                ),
                operation.instrument_id,
            )
            self.diagnostics.append(diagnostic)
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "diagnostics": [*receipt.diagnostics, diagnostic],
                        "summary": {
                            **self._state_event_summary(
                                frame,
                                entry.summary,
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
                self._uncertain = True
            if not receipt_failed:
                diagnostic = _diagnostic(
                    "instrument_state_not_applied",
                    (
                        f"instrument {operation.instrument_id} reported "
                        f"{receipt.status!r} for state operation"
                    ),
                    operation.instrument_id,
                )
                self.diagnostics.append(diagnostic)
                receipt_diagnostics = [*receipt.diagnostics, diagnostic]
            else:
                receipt_diagnostics = list(receipt.diagnostics)
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": (
                            "unknown" if receipt.status == "unknown" else "failed"
                        ),
                        "diagnostics": receipt_diagnostics,
                        "summary": {
                            **self._state_event_summary(
                                frame,
                                entry.summary,
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
            diagnostic = _diagnostic(
                "instrument_apply_state_mismatch",
                "apply receipt state belongs to a different instrument",
                operation.instrument_id,
            )
            self.diagnostics.append(diagnostic)
            self._uncertain = True
            self._append_after_effect(
                entry.model_copy(
                    update={
                        "state": "unknown",
                        "diagnostics": [diagnostic],
                        "summary": {
                            **self._state_event_summary(
                                frame,
                                entry.summary,
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
                    "diagnostics": list(receipt.diagnostics),
                    "summary": {
                        **self._state_event_summary(
                            frame,
                            entry.summary,
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
        stage: str,
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
            summary={
                "request_count": len(operation.command.requests),
                "product_ids": [item.id for item in operation.command.requests],
                **_command_evidence(command),
            },
        )
        self._append(entry)
        try:
            readback = _normalize_readback(
                self.drivers[operation.instrument_id].collect(command)
            )
        except Exception as error:
            self._uncertain = True
            diagnostic = _exception_diagnostic(
                "instrument_collect_unknown",
                "instrument collection outcome is unknown for "
                f"{operation.instrument_id}",
                operation.instrument_id,
                error,
            )
            self.diagnostics.append(diagnostic)
            self._append_transition_best_effort(
                entry.model_copy(
                    update={"state": "unknown", "diagnostics": [diagnostic]}
                )
            )
            return False
        except BaseException as error:
            self._uncertain = True
            diagnostic = self._record_interruption(
                error,
                path=operation.instrument_id,
            )
            self._append_transition_best_effort(
                entry.model_copy(
                    update={"state": "unknown", "diagnostics": [diagnostic]}
                )
            )
            return False
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
            self._uncertain = True
            diagnostic = _exception_diagnostic(
                "collection_readback_commit_failed",
                "collection completed but its readback could not be committed",
                f"operations.{operation.operation_id}.readback",
                error,
            )
            self.diagnostics.append(diagnostic)
            self._append_transition_best_effort(
                entry.model_copy(
                    update={"state": "unknown", "diagnostics": [diagnostic]}
                )
            )
            return False
        except BaseException as error:
            self._uncertain = True
            diagnostic = self._record_interruption(
                error,
                path=f"operations.{operation.operation_id}.readback",
            )
            self._append_transition_best_effort(
                entry.model_copy(
                    update={"state": "unknown", "diagnostics": [diagnostic]}
                )
            )
            return False
        diagnostic_count = len(self.diagnostics)
        self.diagnostics.extend(readback.diagnostics)
        self.diagnostics.extend(_validate_readback(operation, readback))
        if not has_blocking_diagnostics(self.diagnostics[diagnostic_count:]):
            self._merge_readback(frame, operation, readback)
        operation_diagnostics = self.diagnostics[diagnostic_count:]
        failed = has_blocking_diagnostics(operation_diagnostics)
        self._append_after_effect(
            entry.model_copy(
                update={
                    "state": "failed" if failed else "completed",
                    "diagnostics": operation_diagnostics,
                    "summary": {
                        **entry.summary,
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
                self.diagnostics.append(
                    _diagnostic(
                        "instrument_unexpected_product",
                        (
                            f"instrument {operation.instrument_id} returned "
                            f"unexpected product {product_id}"
                        ),
                        f"points.{frame.point.point_index}.products.{product_id}",
                    )
                )
                continue
            if output_id in frame.observables:
                self.diagnostics.append(
                    _diagnostic(
                        "instrument_duplicate_output",
                        f"point received duplicate observable {output_id}",
                        f"points.{frame.point.point_index}.outputs.{output_id}",
                    )
                )
                continue
            frame.observables[output_id] = value

    def _validate_point_outputs(self, frame: _PointFrame) -> None:
        missing = self.program.expected_output_ids - set(frame.observables)
        for output_id in sorted(missing):
            self.diagnostics.append(
                _diagnostic(
                    "instrument_missing_output",
                    f"point {frame.point.point_index} is missing observable "
                    f"{output_id}",
                    f"points.{frame.point.point_index}.outputs.{output_id}",
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
            summary={"observable_ids": sorted(frame.observables)},
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
            diagnostic = _exception_diagnostic(
                "measurement_commit_failed",
                f"failed to commit point {frame.point.point_index} measurement",
                f"points.{frame.point.point_index}.measurement",
                error,
            )
            self.diagnostics.append(diagnostic)
            self._append(
                entry.model_copy(
                    update={"state": "failed", "diagnostics": [diagnostic]}
                )
            )
            return
        self.committed_measurements.append(measurement)
        frame.stats.acquired_record_count += 1
        self._append(entry.model_copy(update={"state": "completed"}))

    def _read_states(self, *, phase: str) -> list[InstrumentStateSnapshot]:
        states: list[InstrumentStateSnapshot] = []
        terminal = phase == "terminal"
        for instrument_id in self.program.resource_order:
            operation_id = f"lifecycle.{phase}-read-state.{instrument_id}"
            entry = self._entry(
                operation_id=operation_id,
                stage=f"{phase}_readback",
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
                diagnostic = _exception_diagnostic(
                    "instrument_readback_failed",
                    f"instrument {phase} readback failed for {instrument_id}",
                    instrument_id,
                    error,
                )
                self.diagnostics.append(diagnostic)
                failed_entry = entry.model_copy(
                    update={"state": "failed", "diagnostics": [diagnostic]}
                )
                if terminal:
                    self._append_transition_best_effort(failed_entry)
                else:
                    self._append_after_effect(failed_entry)
                continue
            except BaseException as error:
                diagnostic = self._record_interruption(
                    error,
                    path=instrument_id,
                )
                self._append_transition_best_effort(
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    )
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
        action = "abort" if has_blocking_diagnostics(self.diagnostics) else "cleanup"
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
                diagnostic = _exception_diagnostic(
                    f"instrument_{action}_failed",
                    f"instrument {action} failed for {instrument_id}",
                    instrument_id,
                    error,
                )
                self.diagnostics.append(diagnostic)
                self._append_transition_best_effort(
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    )
                )
                continue
            except BaseException as error:
                diagnostic = self._record_interruption(
                    error,
                    path=instrument_id,
                )
                self._append_transition_best_effort(
                    entry.model_copy(
                        update={"state": "failed", "diagnostics": [diagnostic]}
                    )
                )
                continue
            self._append_transition_best_effort(
                entry.model_copy(update={"state": "completed"})
            )

    def _capture_terminal_states(self) -> None:
        try:
            self.final_state = self._read_states(phase="terminal")
        except ExecutionJournalError as error:
            self.diagnostics.append(
                _diagnostic(
                    "execution_journal_commit_failed",
                    str(error),
                    "execution.journal",
                )
            )

    def _entry(
        self,
        *,
        operation_id: str,
        stage: str,
        effect: ExecutionEffect,
        state: JournalEntryState,
        point_index: int | None = None,
        instrument_id: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> ExecutionJournalEntry:
        return ExecutionJournalEntry(
            run_id=self.run_id,
            operation_id=operation_id,
            stage=stage,
            effect=effect,
            state=state,
            point_index=point_index,
            instrument_id=instrument_id,
            summary=summary or {},
        )

    def _append(self, entry: ExecutionJournalEntry) -> None:
        self.journal.append(entry)

    def _append_after_effect(self, entry: ExecutionJournalEntry) -> None:
        try:
            self.journal.append(entry)
        except Exception:
            self._uncertain = True
            raise

    def _append_transition_best_effort(self, entry: ExecutionJournalEntry) -> None:
        """Record a transition without allowing evidence failure to block safety."""

        try:
            self.journal.append(entry)
        except Exception as error:
            self._uncertain = True
            self.diagnostics.append(
                _exception_diagnostic(
                    "execution_journal_commit_failed",
                    f"failed to journal {entry.operation_id}",
                    "execution.journal",
                    error,
                )
            )
        except BaseException as error:
            self._uncertain = True
            self._record_interruption(error, path="execution.journal")

    def _observe_payload(self, payload: CommandPayload) -> None:
        if self.payload_observer is None:
            return
        try:
            self.payload_observer(payload)
        except Exception:
            return

    def _record_interruption(
        self,
        error: BaseException,
        *,
        path: str = "execution",
    ) -> Diagnostic:
        if self._interruption is None:
            self._interruption = error
        diagnostic = _diagnostic(
            "execution_interrupted",
            f"execution interrupted by {type(error).__name__}: {error}",
            path,
        )
        self.diagnostics.append(diagnostic)
        return diagnostic

    def _result(self) -> ExecutionEngineResult:
        status = (
            "interrupted"
            if self._interruption is not None
            else "unknown"
            if self._uncertain
            else (
                "failed" if has_blocking_diagnostics(self.diagnostics) else "completed"
            )
        )
        return ExecutionEngineResult(
            run_id=self.run_id,
            experiment_id=self.program.experiment_id,
            status=status,
            diagnostics=tuple(self.diagnostics),
            measurements=tuple(self.committed_measurements),
            initial_state=tuple(self.initial_state),
            final_state=tuple(self.final_state),
            points=tuple(self.point_results),
            uncertain=self._uncertain,
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
) -> dict[str, object]:
    if not dependencies:
        return {}
    return {
        "dependencies": {name: list(values) for name, values in dependencies.items()}
    }


def _validate_readback(
    operation: CollectOperation,
    readback: InstrumentReadback,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    requests = {request.id: request for request in operation.command.requests}
    for product_id in sorted(set(requests) - set(readback.values)):
        diagnostics.append(
            _diagnostic(
                "instrument_missing_product",
                f"instrument {operation.instrument_id} did not return "
                f"requested product {product_id}",
                f"operations.{operation.operation_id}.{product_id}",
            )
        )
    for product_id in sorted(set(readback.values) - set(requests)):
        diagnostics.append(
            _diagnostic(
                "instrument_unexpected_product",
                f"instrument {operation.instrument_id} returned unexpected "
                f"product {product_id}",
                f"operations.{operation.operation_id}.{product_id}",
            )
        )
    for product_id in sorted(set(requests) & set(readback.values)):
        request = requests[product_id]
        value = readback.values[product_id]
        actual_dtype = _readback_dtype(value)
        if not _readback_dtype_compatible(request.dtype, value):
            diagnostics.append(
                _diagnostic(
                    "instrument_readback_dtype_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned {actual_dtype}, expected {request.dtype}",
                    f"operations.{operation.operation_id}.{product_id}.dtype",
                )
            )
        actual_unit = value.unit
        if request.unit is not None and (
            actual_unit is None or not compatible_units(request.unit, actual_unit)
        ):
            diagnostics.append(
                _diagnostic(
                    "instrument_readback_unit_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned unit {actual_unit!r}, expected "
                    f"{request.unit!r}-compatible units",
                    f"operations.{operation.operation_id}.{product_id}.unit",
                )
            )
        expected_shape = [axis.size for axis in request.dimensions]
        actual_shape = value.shape if isinstance(value, MeasurementArray) else []
        if actual_shape != expected_shape:
            diagnostics.append(
                _diagnostic(
                    "instrument_readback_shape_mismatch",
                    f"instrument {operation.instrument_id} product {product_id} "
                    f"returned shape {actual_shape}, expected {expected_shape}",
                    f"operations.{operation.operation_id}.{product_id}.shape",
                )
            )
    return diagnostics


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


def _command_evidence(command: BaseModel) -> dict[str, object]:
    envelope = command.model_dump(mode="json")
    return {
        "command": envelope,
        "command_content_hash": stable_content_hash(envelope),
    }


def _receipt_evidence(receipt: ApplyReceipt) -> dict[str, object]:
    envelope = receipt.model_dump(mode="json")
    return {
        "receipt": envelope,
        "receipt_content_hash": stable_content_hash(envelope),
    }


def _normalize_apply_receipt(value: object) -> ApplyReceipt:
    if not isinstance(value, ApplyReceipt):
        msg = (
            "instrument apply_state must return ApplyReceipt, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return ApplyReceipt.model_validate(value.model_dump(mode="json"))


def _normalize_readback(value: object) -> InstrumentReadback:
    if not isinstance(value, InstrumentReadback):
        msg = (
            "instrument collect must return InstrumentReadback, got "
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
        raise TypeError(msg)
    return InstrumentReadback.model_validate(value.model_dump(mode="json"))


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


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


def _exception_diagnostic(
    code: str,
    message: str,
    path: str,
    error: Exception,
) -> Diagnostic:
    to_diagnostic = getattr(error, "to_diagnostic", None)
    if callable(to_diagnostic):
        converted = to_diagnostic()
        if isinstance(converted, Diagnostic):
            return converted
    return _diagnostic(
        code,
        f"{message}: {type(error).__name__}: {error}",
        path,
    )


__all__ = [
    "ExecutionEngine",
    "ExecutionEngineResult",
    "ExecutionPointStats",
    "NoopResourceLeaseManager",
    "PointExecutionResult",
    "ResourceLeaseManager",
]
