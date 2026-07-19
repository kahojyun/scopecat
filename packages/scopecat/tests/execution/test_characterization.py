from __future__ import annotations

from pathlib import Path
from typing import override

import pytest

import scopecat as sc
from scopecat.adapters.memory import (
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryPayloadEvidenceCommitter,
)
from scopecat.compiler.semantic.model import (
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.execution.effect_interpreter import RunEffectInterpreter
from scopecat.execution.local.program import (
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
    InstrumentActionOperation,
    OutputInput,
    PointProgram,
    StateTarget,
)
from scopecat.execution.program import RunComputeStage, RunPointLoop
from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import ProductUse, ProductUseId, product_id
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    ExecutionTransition,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.instruments import (
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
from tests.testkit.bound_plan import config_with_physical_resources
from tests.testkit.instrument_drivers import SignalInstrumentDriver
from tests.testkit.local_effect_program import (
    StubLocalEffectProgram,
    complete_point_operations,
)


def _logical_point_id(name: str) -> LogicalPointId:
    return LogicalPointId(PointDomainId(name, "root"), 0)


def _claims(*instrument_ids: str) -> tuple[ResourceClaim, ...]:
    return tuple(ResourceClaim(id=instrument_id) for instrument_id in instrument_ids)


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
        system=sc.ExperimentSystem(provider=_SingleDriverProvider(driver)),
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

    program = StubLocalEffectProgram(
        experiment_id="normalized-compute-output",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("normalized-output-point"),
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
        resource_order=(),
        resource_claims=(),
    )

    result = RunEffectInterpreter(
        run_id="normalized-output-run",
        program=program,
        drivers={},
        journal=MemoryExecutionJournal(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "completed"
    assert consumed == [Quantity(value=5.0, unit="GHz")]


def test_run_compute_is_shared_by_every_point_frame() -> None:
    producer_id = OperationId(SymbolId(local_id="run-producer"))
    producer_result_id = operation_result_id(producer_id)
    consumer_id = OperationId(SymbolId(local_id="point-consumer"))
    consumer_result_id = operation_result_id(consumer_id)
    producer_calls = 0
    consumed: list[float] = []

    def produce() -> float:
        nonlocal producer_calls
        producer_calls += 1
        return 2.0

    def consume(*, value: float) -> float:
        consumed.append(value)
        return value + 1.0

    run_stage = RunComputeStage(
        ComputeStage(
            (
                ComputeOperation(
                    operation_id="run.compute.producer",
                    semantic_operation_id=producer_id.qualified_name,
                    implementation_id="python.producer.v1",
                    contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=produce,
                    inputs={},
                    result=ComputeResultSlot(
                        id=producer_result_id,
                        value_type=Scalar(Float()),
                    ),
                ),
            )
        )
    )
    points = tuple(
        PointProgram(
            point_index=index,
            logical_id=LogicalPointId(
                PointDomainId("run-compute-sharing", "root"), index
            ),
            coordinates={},
            stages=(
                ComputeStage(
                    (
                        ComputeOperation(
                            operation_id=f"point-{index}.compute.consumer",
                            semantic_operation_id=consumer_id.qualified_name,
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
        )
        for index in range(2)
    )
    program = StubLocalEffectProgram(
        experiment_id="run-compute-sharing",
        points=points,
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=(),
        resource_claims=(),
    )

    result = RunEffectInterpreter(
        run_id="run-compute-sharing-run",
        program=program,
        drivers={},
        journal=MemoryExecutionJournal(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run((run_stage, RunPointLoop(points)))

    assert result.status == "completed"
    assert producer_calls == 1
    assert consumed == [2.0, 2.0]


def test_distinct_compute_operations_are_each_evaluated() -> None:
    calls: list[str] = []
    first_result_id = operation_result_id(OperationId(SymbolId(local_id="first")))
    second_result_id = operation_result_id(OperationId(SymbolId(local_id="second")))

    def first() -> float:
        calls.append("first")
        return 1.0

    def second() -> float:
        calls.append("second")
        return 2.0

    program = StubLocalEffectProgram(
        experiment_id="implementation-cache-identity",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("implementation-cache-point"),
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
                            ),
                        )
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=(),
        resource_claims=(),
    )

    result = RunEffectInterpreter(
        run_id="implementation-cache-run",
        program=program,
        drivers={},
        journal=MemoryExecutionJournal(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "completed"
    assert calls == ["first", "second"]


class _BlockingStateDriver(SignalInstrumentDriver):
    @override
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
    @override
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

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        return super().read_state()

    @override
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        super().apply_state(command)
        return ApplyReceipt.model_construct(
            status="applied",
            problems=(
                blocking_problem(
                    "instrument_driver_receipt_conflict",
                    "driver bypassed receipt validation",
                    category=ProblemCategory.EXTERNAL_FAILURE,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("instrument", self.instrument_id),
                ),
            ),
        )

    @override
    def abort(self) -> None:
        self.abort_count += 1


class _FinalizationTrackingDriver(SignalInstrumentDriver):
    def __init__(self, *, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.abort_count = 0
        self.read_count = 0

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        return super().read_state()

    @override
    def abort(self) -> None:
        self.abort_count += 1


class _MalformedCollectDriver(SignalInstrumentDriver):
    @override
    def collect(self, command: CollectCommand) -> CollectReceipt:
        super().collect(command)
        return CollectReceipt.model_construct(status="not_collected", problems=())


class _UnknownActionDriver(SignalInstrumentDriver):
    @override
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
            logical_id=_logical_point_id(f"action-point-{index}"),
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
    program = StubLocalEffectProgram(
        experiment_id="action",
        points=points,
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=(driver.instrument_id,),
        resource_claims=_claims(driver.instrument_id),
    )
    result = RunEffectInterpreter(
        run_id="action-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=MemoryExecutionJournal(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.success
    assert result.action_command_count == 2
    assert len(driver.action_commands) == 2


def test_unknown_action_is_not_retried_and_makes_run_indeterminate() -> None:
    driver = _UnknownActionDriver()
    point_uid = "unknown-action-point"
    operation = _action_operation(point_uid, driver.instrument_id)
    journal = MemoryExecutionJournal()
    program = StubLocalEffectProgram(
        experiment_id="unknown-action",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id(point_uid),
                coordinates={},
                stages=(ActionStage(operations=(operation,)),),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=(driver.instrument_id,),
        resource_claims=_claims(driver.instrument_id),
    )
    result = RunEffectInterpreter(
        run_id="unknown-action-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

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

    @override
    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        receipt = super().commit(chunk)
        return receipt.model_copy(update=self._update)


class _BrokenFinalizationJournal(MemoryExecutionJournal):
    @override
    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        if entry.stage == "abort":
            raise RuntimeError("lifecycle journal unavailable")
        return super().append(entry)


def test_invalid_apply_receipt_truth_table_is_rejected_at_normalize_boundary() -> None:
    driver = _MalformedApplyDriver()
    operation = _gain_operation(driver.instrument_id, 1.0)
    program = StubLocalEffectProgram(
        experiment_id="malformed-apply-receipt",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("malformed-apply-point"),
                coordinates={},
                stages=(ApplyStateStage(operations=(operation,)),),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=(driver.instrument_id,),
        resource_claims=_claims(driver.instrument_id),
    )
    journal = MemoryExecutionJournal()

    result = RunEffectInterpreter(
        run_id="malformed-apply-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "unknown"
    assert result.uncertain
    problem_codes = {problem.code for problem in result.problems}
    assert "instrument_apply_unknown" in problem_codes
    assert "instrument_apply_receipt_conflict" not in problem_codes
    assert [
        entry.state
        for entry in journal.entries
        if entry.operation_id == operation.operation_id
    ] == ["started", "unknown"]


def test_invalid_collect_receipt_is_rejected_at_normalize_boundary() -> None:
    driver = _MalformedCollectDriver()
    point_uid = "malformed-collect-point"
    operation = _collect_operation(point_uid, driver.instrument_id, "signal")
    program = StubLocalEffectProgram(
        experiment_id="malformed-collect-readback",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id(point_uid),
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(_collection_product_use("signal"),),
        collection_product_use_ids=(_collection_product_use("signal").id,),
        resource_order=(driver.instrument_id,),
        resource_claims=_claims(driver.instrument_id),
    )
    journal = MemoryExecutionJournal()
    readbacks = MemoryCollectionRepository()

    result = RunEffectInterpreter(
        run_id="malformed-collect-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "unknown"
    assert result.uncertain
    problem_codes = {problem.code for problem in result.problems}
    assert "instrument_collect_unknown" in problem_codes
    assert "instrument_collection_not_completed" not in problem_codes
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
    program = StubLocalEffectProgram(
        experiment_id="mismatched-collection-receipt",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id(point_uid),
                coordinates={},
                stages=(CollectStage(operations=(operation,)),),
            ),
        ),
        product_uses=(_collection_product_use("signal"),),
        collection_product_use_ids=(_collection_product_use("signal").id,),
        resource_order=(driver.instrument_id,),
        resource_claims=_claims(driver.instrument_id),
    )
    journal = MemoryExecutionJournal()
    readbacks = _MismatchedCollectionReceiptRepository(receipt_update)

    result = RunEffectInterpreter(
        run_id="mismatched-collection-receipt-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "unknown"
    assert result.uncertain
    assert len(readbacks.chunks) == 1
    assert len(readbacks.receipts) == 1
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
    program = StubLocalEffectProgram(
        experiment_id="finalization-journal-failure",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("finalization-journal-point"),
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
        resource_order=("source-a", "source-b"),
        resource_claims=_claims("source-a", "source-b"),
    )

    result = RunEffectInterpreter(
        run_id="finalization-journal-run",
        program=program,
        drivers={"source-a": first, "source-b": second},
        journal=_BrokenFinalizationJournal(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

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
    @override
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
    program = StubLocalEffectProgram(
        experiment_id="apply-receipt-evidence",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("apply-receipt-evidence-point"),
                coordinates={},
                stages=(
                    ApplyStateStage(operations=(_gain_operation("source-0", 2.0),)),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        resource_order=("source-0",),
        resource_claims=_claims("source-0"),
    )
    journal = MemoryExecutionJournal()

    result = RunEffectInterpreter(
        run_id="apply-receipt-evidence-run",
        program=program,
        drivers={driver.instrument_id: driver},
        journal=journal,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

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
    program = StubLocalEffectProgram(
        experiment_id="blocking-state",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("blocking-state-point"),
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
        resource_order=("source-a", "source-b"),
        resource_claims=_claims("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    engine = RunEffectInterpreter(
        run_id="blocking-state-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    )

    result = engine.run(complete_point_operations(program))

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
    @override
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


def test_unexpected_product_stops_later_collection_and_fails_journal_entry() -> None:
    first = _UnexpectedProductDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    point_uid = "blocking-collect-point"
    first_operation = _collect_operation(point_uid, "source-a", "first")
    second_operation = _collect_operation(point_uid, "source-b", "second")
    program = StubLocalEffectProgram(
        experiment_id="blocking-collect",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id(point_uid),
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
        resource_order=("source-a", "source-b"),
        resource_claims=_claims("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    readbacks = MemoryCollectionRepository()
    result = RunEffectInterpreter(
        run_id="blocking-collect-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        readbacks=readbacks,
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run(complete_point_operations(program))

    assert result.status == "failed"
    assert [problem.code for problem in result.problems] == [
        "instrument_unexpected_product"
    ]
    assert len(first.collect_commands) == 1
    assert second.collect_commands == []
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
    program = StubLocalEffectProgram(
        experiment_id="conflicting-applied-state",
        points=(
            PointProgram(
                point_index=0,
                logical_id=_logical_point_id("conflicting-applied-state-point"),
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
        resource_order=("source-a", "source-b"),
        resource_claims=_claims("source-a", "source-b"),
    )
    journal = MemoryExecutionJournal()
    engine = RunEffectInterpreter(
        run_id="conflicting-applied-state-run",
        program=program,
        drivers={
            first.instrument_id: first,
            second.instrument_id: second,
        },
        journal=journal,
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    )

    result = engine.run(complete_point_operations(program))

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
