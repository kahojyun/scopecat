from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

import scopecat as sc
from scopecat._content_identity import model_wire_content_hash
from scopecat._execution.engine import ExecutionEngine
from scopecat._execution.journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    ExecutionJournalError,
    ExecutionTransition,
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryPayloadEvidenceCommitter,
)
from scopecat._execution.program import (
    ActionField,
    ActionStage,
    ApplyStateOperation,
    ApplyStateStage,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeResultSlot,
    ComputeStage,
    ExecutionProgram,
    InstrumentActionOperation,
    OutputInput,
    PointProgram,
    RecordProjection,
    StateTarget,
)
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._product_identity import ProductUse, ProductUseId, product_id
from scopecat._semantic_graph import OperationId, operation_result_id
from scopecat._symbols import SymbolId
from scopecat.instruments import (
    ActionReceipt,
    ApplyReceipt,
    CollectCommand,
    CollectProductRequest,
    CollectReceipt,
    InstrumentActionCommand,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
)
from scopecat.measurement_recording import (
    MeasurementRecordChunk,
    MeasurementRecordReceipt,
    MemoryMeasurementRecordCommitter,
)
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef, StateValue
from scopecat.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.value_types import Float, Scalar
from scopecat.value_types import Quantity as QuantityType
from tests.support.experiment_preview import config_with_physical_resources
from tests.support.instrument_drivers import SignalInstrumentDriver


class _SingleDriverProvider:
    def __init__(self, driver: SignalInstrumentDriver) -> None:
        self.driver = driver

    @property
    def provider_id(self) -> str:
        return "tests.execution_characterization"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=(self.driver.describe(),),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        return InstrumentProviderResult(drivers=(self.driver,))


def test_workspace_run_schedules_parent_compute_before_child_consumer(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    source_program_type = sc.ScalarType(sc.PayloadType("source_program"))
    pulse_program_type = sc.ScalarType(sc.PayloadType("pulse_program"))
    program = sc.input("program", source_program_type)
    state_rows = sc.input(
        "state_rows",
        sc.TableType(columns=(sc.TableColumn("slot", sc.ScalarType(sc.IntType())),)),
    )

    def consume(*, program: object) -> dict[str, object]:
        calls.append("consume")
        return {"consumed": program}

    consume_program = sc.compute(
        "consume-program",
        fn=consume,
        inputs={"program": program},
        output_type=pulse_program_type,
    )
    child = (
        sc.module("tests.compute_schedule.child")
        .inputs(program, state_rows)
        .computes(consume_program)
        .state_each(
            state_rows,
            resource="source-0",
            capability="play_program",
            field="program",
            value=consume_program.output,
        )
        .build()
    )

    def produce() -> dict[str, object]:
        calls.append("produce")
        return {"source": "parent"}

    produce_program = sc.compute(
        "produce-program",
        fn=produce,
        output_type=source_program_type,
    )
    parent = (
        sc.module("tests.compute_schedule.parent")
        .computes(produce_program)
        .use(
            child.instantiate(
                "compute-schedule-child",
                program=produce_program.output,
                state_rows=({"slot": 0},),
            )
        )
        .build()
    )
    template = (
        parent.template("tests.compute_schedule", kind="characterization")
        .experiment_id("compute-schedule")
        .build()
    )
    driver = SignalInstrumentDriver()
    lab = sc.open(
        tmp_path,
        config=config_with_physical_resources({"source-0": ("play_program",)}),
        execution_backend=sc.ExecutionBackend(provider=_SingleDriverProvider(driver)),
    )

    run = lab.prepare(template).run()

    assert run.manifest.status == "completed"
    assert calls == ["produce", "consume"]
    assert len(driver.applied) == 1
    applied = driver.applied[0]
    payload_ref = applied.fields[0].value.root
    assert isinstance(payload_ref, PayloadRef)
    command_payload = applied.payloads[payload_ref.payload_id]
    assert command_payload.payload == {"consumed": {"source": "parent"}}
    assert command_payload.evidence_ref is not None
    assert command_payload.evidence_ref.startswith("execution/payloads/")
    assert command_payload.content_hash
    assert (
        tmp_path / "runs" / run.manifest.run_id / command_payload.evidence_ref
    ).is_file()


def test_compute_output_is_normalized_before_downstream_use() -> None:
    consumed: list[Quantity] = []
    producer_id = "normalized-output-point.compute.producer"
    producer_result_id = operation_result_id(OperationId(SymbolId(local_id="producer")))
    consumer_result_id = operation_result_id(OperationId(SymbolId(local_id="consumer")))

    def consume(*, value: Quantity) -> float:
        consumed.append(value)
        return value.value

    program = ExecutionProgram(
        experiment_id="normalized-compute-output",
        points=(
            PointProgram(
                point_index=0,
                point_uid="normalized-output-point",
                coordinates={},
                stages=(
                    ComputeStage(
                        operations=(
                            ComputeOperation(
                                operation_id=producer_id,
                                semantic_operation_id="producer",
                                implementation_id="python.producer.v1",
                                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                                kernel=lambda: Quantity(
                                    value=5000.0,
                                    unit="MHz",
                                ),
                                inputs={},
                                result=ComputeResultSlot(
                                    id=producer_result_id,
                                    value_type=Scalar(QuantityType(unit="GHz")),
                                ),
                            ),
                            ComputeOperation(
                                operation_id=(
                                    "normalized-output-point.compute.consumer"
                                ),
                                semantic_operation_id="consumer",
                                implementation_id="python.consumer.v1",
                                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                                kernel=consume,
                                inputs={"value": OutputInput(producer_result_id)},
                                result=ComputeResultSlot(
                                    id=consumer_result_id,
                                    value_type=Scalar(Float()),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
    )

    result = ExecutionEngine(
        run_id="normalized-output-run",
        program=program,
        drivers={},
        journal=MemoryExecutionJournal(),
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "completed"
    assert consumed == [Quantity(value=5.0, unit="GHz")]


def test_compute_cache_is_partitioned_by_implementation_identity() -> None:
    calls: list[str] = []
    first_result_id = operation_result_id(OperationId(SymbolId(local_id="first")))
    second_result_id = operation_result_id(OperationId(SymbolId(local_id="second")))

    def first() -> float:
        calls.append("first")
        return 1.0

    def second() -> float:
        calls.append("second")
        return 2.0

    program = ExecutionProgram(
        experiment_id="implementation-cache-identity",
        points=(
            PointProgram(
                point_index=0,
                point_uid="implementation-cache-point",
                coordinates={},
                stages=(
                    ComputeStage(
                        operations=(
                            ComputeOperation(
                                operation_id="implementation-cache-point.compute.first",
                                semantic_operation_id="first",
                                implementation_id="python.first.v1",
                                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                                kernel=first,
                                inputs={},
                                result=ComputeResultSlot(
                                    id=first_result_id,
                                    value_type=Scalar(Float()),
                                ),
                                cache_namespace="shared",
                                cache_key="same-inputs",
                            ),
                            ComputeOperation(
                                operation_id="implementation-cache-point.compute.second",
                                semantic_operation_id="second",
                                implementation_id="python.second.v1",
                                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                                kernel=second,
                                inputs={},
                                result=ComputeResultSlot(
                                    id=second_result_id,
                                    value_type=Scalar(Float()),
                                ),
                                cache_namespace="shared",
                                cache_key="same-inputs",
                            ),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
    )

    result = ExecutionEngine(
        run_id="implementation-cache-run",
        program=program,
        drivers={},
        journal=MemoryExecutionJournal(),
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "completed"
    assert calls == ["first", "second"]


class _BlockingStateDriver(SignalInstrumentDriver):
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        return ApplyReceipt(
            status="not_applied",
            problems=(
                blocking_problem(
                    "instrument_driver_blocked",
                    "driver blocked",
                    category=ProblemCategory.EXTERNAL_FAILURE,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("instrument", self.instrument_id),
                ),
            ),
        )


class _UnknownAppliedStateDriver(SignalInstrumentDriver):
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        super().apply_state(command)
        return ApplyReceipt(
            status="unknown",
            problems=(
                blocking_problem(
                    "instrument_driver_applied_with_error",
                    "driver reported an error after applying state",
                    category=ProblemCategory.EXTERNAL_FAILURE,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("instrument", self.instrument_id),
                ),
            ),
        )


class _MalformedApplyDriver(SignalInstrumentDriver):
    def __init__(self, *, instrument_id: str = "source-0") -> None:
        super().__init__(instrument_id=instrument_id)
        self.abort_count = 0
        self.read_count = 0

    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        return super().read_state()

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        super().apply_state(command)
        return cast("ApplyReceipt", object())

    def abort(self) -> None:
        self.abort_count += 1


class _FinalizationTrackingDriver(SignalInstrumentDriver):
    def __init__(self, *, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.abort_count = 0
        self.read_count = 0

    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        return super().read_state()

    def abort(self) -> None:
        self.abort_count += 1


class _MalformedCollectDriver(SignalInstrumentDriver):
    def collect(self, command: CollectCommand) -> CollectReceipt:
        super().collect(command)
        return cast("CollectReceipt", object())


class _UnknownActionDriver(SignalInstrumentDriver):
    def action(self, command: InstrumentActionCommand) -> ActionReceipt:
        self.action_commands.append(command)
        return ActionReceipt(
            status="unknown",
            problems=(
                blocking_problem(
                    code="instrument_action_response_lost",
                    message="action response was lost",
                    category=ProblemCategory.EXTERNAL_FAILURE,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("driver", "action"),
                ),
            ),
        )


def _action_operation(point_uid: str, instrument_id: str) -> InstrumentActionOperation:
    return InstrumentActionOperation(
        operation_id=f"{point_uid}.action.trigger",
        instrument_id=instrument_id,
        capability_id="set_gain",
        fields=(ActionField(id="gain", value=StateValue(1.0)),),
    )


def test_identical_actions_are_delivered_at_every_point() -> None:
    driver = SignalInstrumentDriver()
    points = tuple(
        PointProgram(
            point_index=index,
            point_uid=f"action-point-{index}",
            coordinates={},
            stages=(
                ActionStage(
                    operations=(
                        _action_operation(
                            f"action-point-{index}",
                            driver.instrument_id,
                        ),
                    )
                ),
            ),
        )
        for index in range(2)
    )
    result = ExecutionEngine(
        run_id="action-run",
        program=ExecutionProgram(
            experiment_id="action",
            points=points,
            product_uses=(),
            collection_product_use_ids=(),
            record_projections=(),
            resource_order=(driver.instrument_id,),
        ),
        drivers={driver.instrument_id: driver},
        journal=MemoryExecutionJournal(),
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.success
    assert result.action_command_count == 2
    assert len(driver.action_commands) == 2


def test_unknown_action_is_not_retried_and_makes_run_indeterminate() -> None:
    driver = _UnknownActionDriver()
    point_uid = "unknown-action-point"
    operation = _action_operation(point_uid, driver.instrument_id)
    journal = MemoryExecutionJournal()
    result = ExecutionEngine(
        run_id="unknown-action-run",
        program=ExecutionProgram(
            experiment_id="unknown-action",
            points=(
                PointProgram(
                    point_index=0,
                    point_uid=point_uid,
                    coordinates={},
                    stages=(ActionStage(operations=(operation,)),),
                ),
            ),
            product_uses=(),
            collection_product_use_ids=(),
            record_projections=(),
            resource_order=(driver.instrument_id,),
        ),
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert len(driver.action_commands) == 1
    assert [
        entry.state
        for entry in journal.entries
        if entry.operation_id == operation.operation_id
    ] == ["started", "unknown"]


class _MismatchedCollectionReceiptRepository(MemoryCollectionRepository):
    def __init__(self, update: dict[str, str]) -> None:
        super().__init__()
        self._update = update

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        receipt = super().commit(chunk)
        return receipt.model_copy(update=self._update)


class _BrokenFinalizationJournal(MemoryExecutionJournal):
    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.stage == "abort":
            raise RuntimeError("lifecycle journal unavailable")
        return super().append(entry)


def test_malformed_apply_receipt_is_unknown_and_journaled() -> None:
    driver = _MalformedApplyDriver()
    operation = _gain_operation(driver.instrument_id, 1.0)
    program = ExecutionProgram(
        experiment_id="malformed-apply-receipt",
        points=(
            PointProgram(
                point_index=0,
                point_uid="malformed-apply-point",
                coordinates={},
                stages=(ApplyStateStage(operations=(operation,)),),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=(driver.instrument_id,),
    )
    journal = MemoryExecutionJournal()

    result = ExecutionEngine(
        run_id="malformed-apply-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert "instrument_apply_unknown" in {problem.code for problem in result.problems}
    assert [
        entry.state
        for entry in journal.entries
        if entry.operation_id == operation.operation_id
    ] == ["started", "unknown"]


def test_malformed_collect_readback_is_unknown_and_journaled() -> None:
    driver = _MalformedCollectDriver()
    point_uid = "malformed-collect-point"
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    program = ExecutionProgram(
        experiment_id="malformed-collect-readback",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(_collection_product_use("signal"),),
        collection_product_use_ids=(_collection_product_use("signal").id,),
        record_projections=(_record_projection("signal"),),
        resource_order=(driver.instrument_id,),
    )
    journal = MemoryExecutionJournal()
    readbacks = MemoryCollectionRepository()

    result = ExecutionEngine(
        run_id="malformed-collect-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert "instrument_collect_unknown" in {problem.code for problem in result.problems}
    assert readbacks.chunks == ()
    assert [
        entry.state
        for entry in journal.entries
        if entry.operation_id == operation.operation_id
    ] == ["started", "unknown"]


@pytest.mark.parametrize(
    "receipt_update",
    [
        {"operation_id": "wrong-operation"},
        {"content_hash": "wrong-chunk-hash"},
    ],
)
def test_mismatched_collection_receipt_is_indeterminate(
    receipt_update: dict[str, str],
) -> None:
    driver = SignalInstrumentDriver()
    point_uid = "mismatched-collection-receipt-point"
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    program = ExecutionProgram(
        experiment_id="mismatched-collection-receipt",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(_collection_product_use("signal"),),
        collection_product_use_ids=(_collection_product_use("signal").id,),
        record_projections=(_record_projection("signal"),),
        resource_order=(driver.instrument_id,),
    )
    journal = MemoryExecutionJournal()
    readbacks = _MismatchedCollectionReceiptRepository(receipt_update)

    result = ExecutionEngine(
        run_id="mismatched-collection-receipt-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert len(readbacks.chunks) == 1
    assert len(readbacks.receipts) == 1
    assert result.measurements == ()
    assert "collection_readback_commit_failed" in {
        problem.code for problem in result.problems
    }
    assert [
        entry.state
        for entry in journal.entries
        if entry.operation_id == operation.operation_id
    ] == ["started", "unknown"]


def test_finalization_journal_failure_cannot_block_abort_or_terminal_read() -> None:
    first = _MalformedApplyDriver(instrument_id="source-a")
    second = _FinalizationTrackingDriver(instrument_id="source-b")
    program = ExecutionProgram(
        experiment_id="finalization-journal-failure",
        points=(
            PointProgram(
                point_index=0,
                point_uid="finalization-journal-point",
                coordinates={},
                stages=(
                    ApplyStateStage(
                        operations=(
                            _gain_operation("source-a", 1.0),
                            _gain_operation("source-b", 2.0),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=("source-a", "source-b"),
    )

    result = ExecutionEngine(
        run_id="finalization-journal-run",
        program=program,
        drivers={"source-a": first, "source-b": second},
        journal=_BrokenFinalizationJournal(),
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert first.abort_count == 1
    assert second.abort_count == 1
    assert first.read_count == 2
    assert second.read_count == 2
    assert {state.instrument_id for state in result.final_state} == {
        "source-a",
        "source-b",
    }
    assert "execution_journal_commit_failed" in {
        problem.code for problem in result.problems
    }


class _ReceiptEvidenceStateDriver(SignalInstrumentDriver):
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        super().apply_state(command)
        return ApplyReceipt(
            status="applied",
            state=self.read_state(),
            metadata={
                "controller": {"sequence": 17, "confirmed": True},
            },
        )


def test_apply_journal_persists_full_receipt_evidence() -> None:
    driver = _ReceiptEvidenceStateDriver()
    program = ExecutionProgram(
        experiment_id="apply-receipt-evidence",
        points=(
            PointProgram(
                point_index=0,
                point_uid="apply-receipt-evidence-point",
                coordinates={},
                stages=(
                    ApplyStateStage(operations=(_gain_operation("source-0", 2.0),)),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=("source-0",),
    )
    journal = MemoryExecutionJournal()

    result = ExecutionEngine(
        run_id="apply-receipt-evidence-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "completed"
    completed = next(
        entry
        for entry in journal.entries
        if entry.stage == "apply_state" and entry.state == "completed"
    )
    receipt = completed.evidence["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["status"] == "applied"
    assert receipt["metadata"] == {"controller": {"sequence": 17, "confirmed": True}}
    receipt_state = receipt["state"]
    assert isinstance(receipt_state, dict)
    assert receipt_state["instrument_id"] == "source-0"
    assert completed.evidence["receipt_content_hash"] == model_wire_content_hash(
        ApplyReceipt.model_validate(receipt)
    )


def test_state_apply_stops_on_blocking_result_without_committing_state() -> None:
    first = _BlockingStateDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    program = ExecutionProgram(
        experiment_id="blocking-state",
        points=(
            PointProgram(
                point_index=0,
                point_uid="blocking-state-point",
                coordinates={},
                stages=(
                    ApplyStateStage(
                        operations=(
                            _gain_operation("source-a", 1.0),
                            _gain_operation("source-b", 2.0),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    engine = ExecutionEngine(
        run_id="blocking-state-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    )

    result = engine.run()

    assert result.status == "failed"
    assert [problem.code for problem in result.problems] == [
        "instrument_driver_blocked"
    ]
    assert len(first.applied) == 1
    assert second.applied == []
    assert (
        tuple(
            engine.current_states[instrument_id]
            for instrument_id in program.resource_order
        )
        == result.initial_state
    )
    assert result.final_state == result.initial_state
    assert result.changed_field_count == 0
    assert result.state_command_count == 0
    assert result.points[0].result == "failed"
    assert [
        (entry.operation_id, entry.state)
        for entry in journal.entries
        if entry.stage == "apply_state"
    ] == [
        ("blocking-state-point.state.source-a", "started"),
        ("blocking-state-point.state.source-a", "failed"),
    ]
    started = next(
        entry
        for entry in journal.entries
        if entry.operation_id == "blocking-state-point.state.source-a"
        and entry.state == "started"
    )
    command = started.evidence["command"]
    assert isinstance(command, dict)
    assert command["operation_id"] == started.operation_id
    assert started.evidence["command_content_hash"]


class _UnexpectedProductDriver(SignalInstrumentDriver):
    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        return CollectReceipt(
            readback=InstrumentReadback(
                values={
                    "signal": Quantity(value=1.0, unit="ratio"),
                    "unexpected": Quantity(value=2.0, unit="ratio"),
                }
            )
        )


def test_one_collected_product_projects_to_two_record_aliases() -> None:
    driver = SignalInstrumentDriver()
    point_uid = "record-alias-point"
    use = _collection_product_use("shared")
    operation = _collect_operation(point_uid, driver.instrument_id, "shared")
    measurements = MemoryMeasurementRecordCommitter()
    readbacks = MemoryCollectionRepository()
    journal = MemoryExecutionJournal()
    program = ExecutionProgram(
        experiment_id="record-alias",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(use,),
        collection_product_use_ids=(use.id,),
        record_projections=(
            RecordProjection(
                record_id="primary",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
            RecordProjection(
                record_id="secondary",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
        ),
        resource_order=(driver.instrument_id,),
    )

    result = ExecutionEngine(
        run_id="record-alias-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=measurements,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "completed"
    assert len(driver.collect_commands) == 1
    assert len(measurements.chunks) == 1
    recorded = measurements.chunks[0].record
    assert set(recorded.observables) == {"primary", "secondary"}
    assert recorded.observables["primary"] == recorded.observables["secondary"]
    collection_started = next(
        entry
        for entry in journal.entries
        if entry.stage == "collect" and entry.state == "started"
    )
    collection_completed = next(
        entry
        for entry in journal.entries
        if entry.stage == "collect" and entry.state == "completed"
    )
    collection_chunk = readbacks.chunks[0]
    collection_receipt = readbacks.receipts[0]
    assert collection_chunk.operation_id == collection_receipt.operation_id
    assert (
        collection_started.evidence["command_content_hash"]
        == collection_chunk.command_content_hash
    )
    assert (
        collection_completed.evidence["readback_content_hash"]
        == collection_chunk.content_hash
        == collection_receipt.content_hash
    )
    assert collection_completed.evidence["receipt_status"] == "collected"
    assert "receipt" not in collection_completed.evidence
    completed = next(
        entry
        for entry in journal.entries
        if entry.stage == "record_measurement" and entry.state == "completed"
    )
    receipt = measurements.receipts[0]
    assert completed.operation_id == receipt.operation_id
    assert completed.evidence["record_ref"] == receipt.record_ref
    assert completed.evidence["chunk_content_hash"] == receipt.chunk_content_hash
    assert completed.evidence["receipt_content_hash"] == receipt.content_hash


class _FailMeasurementCompletionJournal(MemoryExecutionJournal):
    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.stage == "record_measurement" and entry.state == "completed":
            raise ExecutionJournalError("measurement completion journal unavailable")
        return super().append(entry)


class _NoSequenceMeasurementJournal(MemoryExecutionJournal):
    def __init__(self) -> None:
        super().__init__()
        self.recording_attempts: list[ExecutionTransition] = []

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.stage == "record_measurement":
            self.recording_attempts.append(entry.model_copy(deep=True))
            return entry.model_copy(deep=True)
        return super().append(entry)


class _MutatingMeasurementJournal(MemoryExecutionJournal):
    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.stage == "record_measurement":
            return super().append(
                entry.model_copy(update={"evidence": {"mutated": True}})
            )
        return super().append(entry)


@pytest.mark.parametrize(
    "journal_type",
    (_NoSequenceMeasurementJournal, _MutatingMeasurementJournal),
)
def test_invalid_measurement_started_commit_prevents_record_write(
    journal_type: type[MemoryExecutionJournal],
) -> None:
    driver = SignalInstrumentDriver()
    point_uid = "invalid-measurement-started-point"
    use = _collection_product_use("signal")
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    measurements = MemoryMeasurementRecordCommitter()
    journal = journal_type()
    program = ExecutionProgram(
        experiment_id="invalid-measurement-started",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(use,),
        collection_product_use_ids=(use.id,),
        record_projections=(
            RecordProjection(
                record_id="signal",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
        ),
        resource_order=(driver.instrument_id,),
    )

    result = ExecutionEngine(
        run_id="invalid-measurement-started-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=measurements,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    attempted = tuple(
        entry
        for entry in (
            *journal.entries,
            *getattr(journal, "recording_attempts", ()),
        )
        if entry.stage == "record_measurement"
    )
    assert result.status == "failed"
    assert not result.uncertain
    assert measurements.chunks == ()
    assert attempted
    assert all(entry.state != "completed" for entry in attempted)


def test_measurement_receipt_followed_by_journal_failure_is_indeterminate() -> None:
    driver = SignalInstrumentDriver()
    point_uid = "measurement-journal-failure-point"
    use = _collection_product_use("signal")
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    measurements = MemoryMeasurementRecordCommitter()
    journal = _FailMeasurementCompletionJournal()
    program = ExecutionProgram(
        experiment_id="measurement-journal-failure",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(use,),
        collection_product_use_ids=(use.id,),
        record_projections=(
            RecordProjection(
                record_id="signal",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
        ),
        resource_order=(driver.instrument_id,),
    )

    result = ExecutionEngine(
        run_id="measurement-journal-failure-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=measurements,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert len(measurements.receipts) == 1
    assert len(result.measurements) == 1
    assert "execution_journal_commit_failed" in {
        problem.code for problem in result.problems
    }
    assert [
        entry.state for entry in journal.entries if entry.stage == "record_measurement"
    ] == ["started"]


class _MismatchedMeasurementReceiptCommitter(MemoryMeasurementRecordCommitter):
    def commit(self, chunk: MeasurementRecordChunk) -> MeasurementRecordReceipt:
        receipt = super().commit(chunk)
        return receipt.model_copy(update={"chunk_content_hash": "wrong-chunk-hash"})


def test_mismatched_measurement_receipt_is_indeterminate() -> None:
    driver = SignalInstrumentDriver()
    point_uid = "mismatched-measurement-receipt-point"
    use = _collection_product_use("signal")
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    measurements = _MismatchedMeasurementReceiptCommitter()
    journal = MemoryExecutionJournal()
    program = ExecutionProgram(
        experiment_id="mismatched-measurement-receipt",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(use,),
        collection_product_use_ids=(use.id,),
        record_projections=(
            RecordProjection(
                record_id="signal",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
        ),
        resource_order=(driver.instrument_id,),
    )

    result = ExecutionEngine(
        run_id="mismatched-measurement-receipt-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        measurements=measurements,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "unknown"
    assert result.uncertain
    assert len(measurements.receipts) == 1
    assert result.measurements == ()
    assert "measurement_commit_failed" in {problem.code for problem in result.problems}
    assert [
        entry.state for entry in journal.entries if entry.stage == "record_measurement"
    ] == ["started", "unknown"]


def test_unexpected_product_stops_later_collection_and_fails_journal_entry() -> None:
    first = _UnexpectedProductDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    point_uid = "blocking-collect-point"
    first_operation = _collect_operation(point_uid, "source-a", "first")
    second_operation = _collect_operation(point_uid, "source-b", "second")
    program = ExecutionProgram(
        experiment_id="blocking-collect",
        points=(
            PointProgram(
                point_index=0,
                point_uid=point_uid,
                coordinates={},
                stages=(CollectStage(operations=(first_operation, second_operation)),),
            ),
        ),
        product_uses=(
            _collection_product_use("first"),
            _collection_product_use("second"),
        ),
        collection_product_use_ids=(
            _collection_product_use("first").id,
            _collection_product_use("second").id,
        ),
        record_projections=(
            _record_projection("first"),
            _record_projection("second"),
        ),
        resource_order=("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    measurements = MemoryMeasurementRecordCommitter()
    readbacks = MemoryCollectionRepository()
    result = ExecutionEngine(
        run_id="blocking-collect-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        measurements=measurements,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "failed"
    assert [problem.code for problem in result.problems] == [
        "instrument_unexpected_product"
    ]
    assert len(first.collect_commands) == 1
    assert second.collect_commands == []
    assert measurements.chunks == ()
    assert len(readbacks.chunks) == 1
    assert set(readbacks.chunks[0].readback.values) == {"signal", "unexpected"}
    assert [
        (entry.operation_id, entry.state)
        for entry in journal.entries
        if entry.stage == "collect"
    ] == [
        (first_operation.operation_id, "started"),
        (first_operation.operation_id, "failed"),
    ]
    failed_entry = next(
        entry
        for entry in journal.entries
        if entry.operation_id == first_operation.operation_id
        and entry.state == "failed"
    )
    assert failed_entry.evidence["readback_ref"]
    assert failed_entry.evidence["readback_content_hash"]


def test_unknown_receipt_with_blocking_problem_does_not_advance_state() -> None:
    first = _UnknownAppliedStateDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    program = ExecutionProgram(
        experiment_id="conflicting-applied-state",
        points=(
            PointProgram(
                point_index=0,
                point_uid="conflicting-applied-state-point",
                coordinates={},
                stages=(
                    ApplyStateStage(
                        operations=(
                            ApplyStateOperation(
                                operation_id=(
                                    "conflicting-applied-state-point.state.source-a"
                                ),
                                instrument_id="source-a",
                                targets=(
                                    StateTarget(
                                        capability_id="set_gain",
                                        field_path="gain",
                                        value=StateValue(1.0),
                                    ),
                                ),
                            ),
                            ApplyStateOperation(
                                operation_id=(
                                    "conflicting-applied-state-point.state.source-b"
                                ),
                                instrument_id="source-b",
                                targets=(
                                    StateTarget(
                                        capability_id="set_gain",
                                        field_path="gain",
                                        value=StateValue(2.0),
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    engine = ExecutionEngine(
        run_id="conflicting-applied-state-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    )

    result = engine.run()

    assert result.status == "unknown"
    assert result.uncertain
    assert [problem.code for problem in result.problems] == [
        "instrument_driver_applied_with_error",
    ]
    assert len(first.applied) == 1
    assert second.applied == []
    assert engine.current_states["source-a"] == result.initial_state[0]
    assert result.final_state[0] != result.initial_state[0]
    assert result.final_state[0].fields[0].value == StateValue(1.0)
    assert result.changed_field_count == 0
    assert result.state_command_count == 0
    assert [
        (entry.operation_id, entry.state)
        for entry in journal.entries
        if entry.stage == "apply_state"
    ] == [
        ("conflicting-applied-state-point.state.source-a", "started"),
        ("conflicting-applied-state-point.state.source-a", "unknown"),
    ]


def _gain_operation(instrument_id: str, value: float) -> ApplyStateOperation:
    return ApplyStateOperation(
        operation_id=f"blocking-state-point.state.{instrument_id}",
        instrument_id=instrument_id,
        targets=(
            StateTarget(
                capability_id="set_gain",
                field_path="gain",
                value=StateValue(value),
            ),
        ),
    )


def _collect_operation(
    point_uid: str,
    instrument_id: str,
    output_id: str,
) -> CollectOperation:
    use = _collection_product_use(output_id)
    operation_id = f"{point_uid}.collect.{instrument_id}"
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=instrument_id,
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id=instrument_id,
            point_index=0,
            point_count=1,
            requests=[CollectProductRequest(id="signal")],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key="signal",
                product_use_id=use.id,
                product_id=use.product_id,
            ),
        ),
    )


def _collection_product_use(output_id: str) -> ProductUse:
    return ProductUse(
        product_id=product_id("signal"),
        id=ProductUseId(f"record:{output_id}"),
    )


def _record_projection(output_id: str) -> RecordProjection:
    use = _collection_product_use(output_id)
    return RecordProjection(
        record_id=output_id,
        product_use_id=use.id,
        product_id=use.product_id,
    )
