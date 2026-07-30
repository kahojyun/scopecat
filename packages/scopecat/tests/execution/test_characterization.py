from __future__ import annotations

from pathlib import Path
from typing import Annotated, override

import scopecat as sc
from scopecat.execution.effect_interpreter import RunEffectInterpreter
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectionResultBinding,
    CollectOperation,
    ComputeOperation,
    OutputInput,
    StateTarget,
)
from scopecat.execution.program import RunCoverageCheckpoint
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.kernel.product_identity import ProductUse, ProductUseId, product_id
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import ResourceRequirement
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverOutcome,
    DriverPayload,
    DriverReadback,
    DriverRejected,
    DriverState,
    DriverStatePatch,
    DriverSuccess,
    DriverUnknown,
    InstrumentConnectionContext,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InterfaceRef,
)
from scopecat.sdk.instruments.commands import CollectCommand, CollectResultRequest
from tests.testkit.in_process_lab import in_process_lab
from tests.testkit.instrument_drivers import SignalInstrumentDriver
from tests.testkit.instrument_host import (
    TestRunInstrumentHost,
    compose_test_instruments,
)
from tests.testkit.local_materialization import LocalEffectInspection
from tests.testkit.materialized_effects import config_with_physical_resources
from tests.testkit.payload_codecs import json_payload_codecs
from tests.testkit.run_operations import complete_coverage_operations
from tests.testkit.runtime import FakeExecutionJournal

_PLAY_PROGRAM = InterfaceRef("test.play_program/v1")
_PLAY_PROGRAM_PLAY = _PLAY_PROGRAM.operation("play")
_PLAY_PROGRAM_ARGUMENT = _PLAY_PROGRAM_PLAY.argument("program")

type _SourceProgramInput = Annotated[
    sc.Input[object],
    sc.ScalarType(sc.PayloadType("source_program")),
]


def _logical_point_id(name: str, ordinal: int = 0) -> LogicalPointId:
    return LogicalPointId(PointDomainId(name, "root"), ordinal)


def _requirements(*instrument_ids: str) -> tuple[ResourceRequirement, ...]:
    return tuple(
        ResourceRequirement(id=instrument_id) for instrument_id in instrument_ids
    )


def test_coverage_iterator_is_consumed_after_each_checkpoint() -> None:
    delivered: list[tuple[int, ...]] = []
    points = tuple(
        RunPoint(_logical_point_id("incremental-source", ordinal), {})
        for ordinal in range(2)
    )

    def operations():
        yield RunCoverageCheckpoint(0)
        assert delivered == [(0,)]
        yield RunCoverageCheckpoint(1)

    result = RunEffectInterpreter(
        run_id="incremental-source-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost(),
        journal=FakeExecutionJournal(),
        coverage_observer=lambda selected, _candidates: delivered.append(
            tuple(point.ordinal for point in selected)
        ),
    ).run(operations(), points=points)

    assert not result.problems
    assert delivered == [(0,), (1,)]
    assert result.admitted_points == points


def test_normal_completion_applies_postcondition_after_point_coverage() -> None:
    driver = SignalInstrumentDriver(instrument_id="source-0")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("postcondition-point"), {}),
        (_gain_operation("source-0", 1.0),),
        resource_order=("source-0",),
        resource_requirements=_requirements("source-0"),
    )

    result = RunEffectInterpreter(
        run_id="postcondition-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost((driver,)),
        journal=FakeExecutionJournal(),
    ).run(
        complete_coverage_operations(program),
        points=program.points,
        postcondition=(_gain_operation("source-0", 0.0),),
    )

    assert not result.problems and not result.indeterminate
    assert len(driver.applied) == 2
    [final] = result.final_state
    assert next(
        item.value
        for item in final.properties
        if item.interface_id == "test.set_gain/v1" and item.property_id == "gain"
    ) == StateValue(0.0)


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

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> SignalInstrumentDriver:
        assert context.binding.id == self.driver.instrument_id
        return self.driver


def test_project_run_schedules_parent_compute_before_child_consumer(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    source_program_type = sc.ScalarType(sc.PayloadType("source_program"))
    pulse_program_type = sc.ScalarType(sc.PayloadType("pulse_program"))

    def consume(*, program: object) -> dict[str, object]:
        calls.append("consume")
        return {"consumed": program}

    @sc.module(id="tests.compute_schedule.child")
    def child(
        context: sc.ModuleContext,
        program: _SourceProgramInput,
    ) -> None:
        consumed = context.compute(
            "consume-program",
            fn=consume,
            inputs={"program": sc.input_ref(program)},
            output_type=pulse_program_type,
        )
        source = context.resource("source", requires=(_PLAY_PROGRAM,))
        context.invoke(
            "play-program",
            resource=source,
            operation=_PLAY_PROGRAM_PLAY,
            arguments={_PLAY_PROGRAM_ARGUMENT: consumed},
        )

    def produce() -> dict[str, object]:
        calls.append("produce")
        return {"source": "parent"}

    @sc.module(id="tests.compute_schedule.parent")
    def parent(context: sc.ModuleContext) -> None:
        produced = context.compute(
            "produce-program",
            fn=produce,
            output_type=source_program_type,
        )
        context.call(
            child.instantiate(
                "compute-schedule-child",
                program=produced,
            )
        )

    @sc.template(
        id="tests.compute_schedule",
        kind="characterization",
    )
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.run(parent())

    driver = SignalInstrumentDriver()
    payload_codecs = json_payload_codecs("pulse_program")
    config = config_with_physical_resources({"source-0": ("test.play_program/v1",)})
    composition = compose_test_instruments(
        config=config,
        provider=_SingleDriverProvider(driver),
        payload_codecs=payload_codecs,
    )
    lab = in_process_lab(
        tmp_path,
        config=config,
        system=composition.system,
        instrument_backend=composition.backend,
    )

    run = lab.prepare(template).run()

    assert run.manifest.status == "completed"
    assert calls == ["produce", "consume"]
    assert len(driver.invoked) == 1
    invoked = driver.invoked[0]
    [argument] = invoked.arguments.values()
    assert isinstance(argument, DriverPayload)
    assert argument.schema_id == "pulse_program"
    assert argument.value == {"consumed": {"source": "parent"}}


def test_compute_output_is_normalized_before_downstream_use() -> None:
    consumed: list[Quantity] = []
    producer_id = "normalized-output-point.compute.producer"
    producer_result_id = operation_result_id(OperationId(SymbolId(local_id="producer")))
    consumer_result_id = operation_result_id(OperationId(SymbolId(local_id="consumer")))

    def consume(*, value: Quantity) -> float:
        consumed.append(value)
        return value.value

    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("normalized-output-point"), {}),
        (
            ComputeOperation(
                operation_id=producer_id,
                semantic_operation_id="producer",
                implementation_id="python.producer.v1",
                kernel=lambda: Quantity(
                    value=5000.0,
                    unit="MHz",
                ),
                inputs={},
                result=ComputeOutput(
                    id=producer_result_id,
                    value_type=Scalar(QuantityType(unit="GHz")),
                ),
            ),
            ComputeOperation(
                operation_id=("normalized-output-point.compute.consumer"),
                semantic_operation_id="consumer",
                implementation_id="python.consumer.v1",
                kernel=consume,
                inputs={"value": OutputInput(producer_result_id)},
                result=ComputeOutput(
                    id=consumer_result_id,
                    value_type=Scalar(Float()),
                ),
            ),
        ),
        resource_order=(),
        resource_requirements=(),
    )

    result = RunEffectInterpreter(
        run_id="normalized-output-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost(),
        journal=FakeExecutionJournal(),
    ).run(complete_coverage_operations(program), points=program.points)

    assert not result.problems and not result.indeterminate
    assert consumed == [Quantity(value=5.0, unit="GHz")]


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

    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("implementation-cache-point"), {}),
        (
            ComputeOperation(
                operation_id="implementation-cache-point.compute.first",
                semantic_operation_id="first",
                implementation_id="python.first.v1",
                kernel=first,
                inputs={},
                result=ComputeOutput(
                    id=first_result_id,
                    value_type=Scalar(Float()),
                ),
            ),
            ComputeOperation(
                operation_id="implementation-cache-point.compute.second",
                semantic_operation_id="second",
                implementation_id="python.second.v1",
                kernel=second,
                inputs={},
                result=ComputeOutput(
                    id=second_result_id,
                    value_type=Scalar(Float()),
                ),
            ),
        ),
        resource_order=(),
        resource_requirements=(),
    )

    result = RunEffectInterpreter(
        run_id="implementation-cache-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost(),
        journal=FakeExecutionJournal(),
    ).run(complete_coverage_operations(program), points=program.points)

    assert not result.problems and not result.indeterminate
    assert calls == ["first", "second"]


class _BlockingStateDriver(SignalInstrumentDriver):
    @override
    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        self.applied.append(request)
        return DriverRejected(
            problems=(
                problem(
                    "instrument_driver_blocked",
                    "driver blocked",
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("instrument", self.instrument_id),
                ),
            ),
        )


class _UnknownAppliedStateDriver(SignalInstrumentDriver):
    @override
    def apply_state(
        self,
        request: DriverStatePatch,
    ) -> DriverOutcome[DriverState | None]:
        super().apply_state(request)
        return DriverUnknown(
            problems=(
                problem(
                    "instrument_driver_applied_with_error",
                    "driver reported an error after applying state",
                    phase=ProblemPhase.EXECUTION,
                    location=model_location("instrument", self.instrument_id),
                ),
            ),
        )


class _FinalizationTrackingDriver(SignalInstrumentDriver):
    def __init__(self, *, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.abort_count = 0
        self.disconnect_count = 0
        self.read_count_when_disconnected: int | None = None
        self.read_count = 0

    @override
    def read_state(self) -> DriverState:
        self.read_count += 1
        return super().read_state()

    @override
    def abort(self) -> None:
        self.abort_count += 1

    @override
    def disconnect(self) -> None:
        self.disconnect_count += 1
        self.read_count_when_disconnected = self.read_count


class _DisconnectFailureDriver(_FinalizationTrackingDriver):
    @override
    def disconnect(self) -> None:
        super().disconnect()
        raise RuntimeError("socket disconnect failed")


def test_one_provider_readback_fans_out_to_every_logical_product_use() -> None:
    driver = SignalInstrumentDriver()
    point = RunPoint(_logical_point_id("shared-readback-point"), {})
    uses = (
        _collection_product_use("first-signal-use"),
        _collection_product_use("second-signal-use"),
    )
    operation_id = "shared-readback-point.collect.source-0"
    operation = CollectOperation(
        operation_id=operation_id,
        instrument_id=driver.instrument_id,
        command=CollectCommand(
            command_id=operation_id,
            instrument_id=driver.instrument_id,
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="signal",
                    interface_id="test.scalar_signal/v1",
                    acquisition_id="sample",
                    result_id="signal",
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                request_id="signal",
                product_use_ids=tuple(use.id for use in uses),
            ),
        ),
    )
    program = LocalEffectInspection.at_point(
        point,
        (operation,),
        resource_order=(driver.instrument_id,),
        resource_requirements=_requirements(driver.instrument_id),
    )
    observed_candidates: list[tuple[MeasurementValueCandidate, ...]] = []
    result = RunEffectInterpreter(
        run_id="shared-readback-run",
        coordinate_ids=tuple(point.coordinates),
        instruments=TestRunInstrumentHost((driver,)),
        journal=FakeExecutionJournal(),
        coverage_observer=lambda _block, candidates: observed_candidates.append(
            candidates
        ),
    ).run(complete_coverage_operations(program), points=program.points)

    assert not result.problems and not result.indeterminate
    assert len(driver.collect_requests) == 1
    assert [result.result_id for result in driver.collect_requests[0].results] == [
        "signal"
    ]
    [candidates] = observed_candidates
    assert [
        (candidate.logical_point_id, candidate.product_use_id, candidate.value)
        for candidate in candidates
    ] == [
        (
            point.logical_id,
            use.id,
            MeasurementScalar.create(
                dtype="float64",
                value=1.0,
                unit="ratio",
            ),
        )
        for use in uses
    ]
    evidence = candidates[0].evidence
    assert evidence is not None
    assert evidence.command_id == operation_id
    assert evidence.instrument_id == driver.instrument_id
    assert evidence.acquisition_id == "sample"
    assert evidence.result_id == "signal"
    assert all(candidate.evidence == evidence for candidate in candidates)


def test_driver_disconnect_failure_is_reported_after_terminal_read() -> None:
    driver = _DisconnectFailureDriver(instrument_id="source-0")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("disconnect-failure-point"), {}),
        (_gain_operation("source-0", 1.0),),
        resource_order=("source-0",),
        resource_requirements=_requirements("source-0"),
    )

    result = RunEffectInterpreter(
        run_id="disconnect-failure-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost((driver,)),
        journal=FakeExecutionJournal(),
    ).run(complete_coverage_operations(program), points=program.points)

    assert driver.disconnect_count == 1
    assert driver.read_count_when_disconnected == 3
    assert "hardware_finalization_unknown" in {item.code for item in result.problems}


def test_state_apply_stops_on_blocking_result_without_committing_state() -> None:
    first = _BlockingStateDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("blocking-state-point"), {}),
        (
            _gain_operation("source-a", 1.0),
            _gain_operation("source-b", 2.0),
        ),
        resource_order=("source-a", "source-b"),
        resource_requirements=_requirements("source-a", "source-b"),
    )
    engine = RunEffectInterpreter(
        run_id="blocking-state-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost((first, second)),
        journal=FakeExecutionJournal(),
    )

    result = engine.run(complete_coverage_operations(program), points=program.points)

    assert result.problems and not result.indeterminate
    assert [problem.code for problem in result.problems] == [
        "instrument_driver_blocked"
    ]
    assert len(first.applied) == 1
    assert second.applied == []
    assert result.final_state == result.prepared_state


def test_failed_coverage_does_not_apply_normal_completion_postcondition() -> None:
    driver = _BlockingStateDriver(instrument_id="source-0")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("failed-postcondition-point"), {}),
        (_gain_operation("source-0", 1.0),),
        resource_order=("source-0",),
        resource_requirements=_requirements("source-0"),
    )

    result = RunEffectInterpreter(
        run_id="failed-postcondition-run",
        coordinate_ids=(),
        instruments=TestRunInstrumentHost((driver,)),
        journal=FakeExecutionJournal(),
    ).run(
        complete_coverage_operations(program),
        points=program.points,
        postcondition=(_gain_operation("source-0", 0.0),),
    )

    assert result.problems
    assert len(driver.applied) == 1


class _UnexpectedResultDriver(SignalInstrumentDriver):
    @override
    def collect(
        self,
        request: DriverAcquisition,
    ) -> DriverOutcome[DriverReadback]:
        self.collect_requests.append(request)
        signal = request.target.result("signal")
        return DriverSuccess(
            DriverReadback(
                values={
                    signal: MeasurementScalar.create(
                        dtype="float64",
                        value=1.0,
                        unit="ratio",
                    ),
                    request.target.result("unexpected"): MeasurementScalar.create(
                        dtype="float64",
                        value=2.0,
                        unit="ratio",
                    ),
                }
            ),
        )


def test_unexpected_result_stops_later_collection() -> None:
    first = _UnexpectedResultDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    point_uid = "blocking-collect-point"
    first_operation = _collect_operation(point_uid, "source-a", "first")
    second_operation = _collect_operation(point_uid, "source-b", "second")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id(point_uid), {}),
        (first_operation, second_operation),
        resource_order=("source-a", "source-b"),
        resource_requirements=_requirements("source-a", "source-b"),
    )
    result = RunEffectInterpreter(
        run_id="blocking-collect-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost((first, second)),
        journal=FakeExecutionJournal(),
    ).run(complete_coverage_operations(program), points=program.points)

    assert result.problems and not result.indeterminate
    assert [problem.code for problem in result.problems] == [
        "instrument_unexpected_product"
    ]
    assert len(first.collect_requests) == 1
    assert second.collect_requests == []


def test_unknown_receipt_with_problem_does_not_advance_state() -> None:
    first = _UnknownAppliedStateDriver(instrument_id="source-a")
    second = SignalInstrumentDriver(instrument_id="source-b")
    program = LocalEffectInspection.at_point(
        RunPoint(_logical_point_id("conflicting-applied-state-point"), {}),
        (
            ApplyStateOperation(
                operation_id=("conflicting-applied-state-point.state.source-a"),
                instrument_id="source-a",
                targets=(
                    StateTarget(
                        interface_id="test.set_gain/v1",
                        property_id="gain",
                        value=StateValue(1.0),
                    ),
                ),
            ),
            ApplyStateOperation(
                operation_id=("conflicting-applied-state-point.state.source-b"),
                instrument_id="source-b",
                targets=(
                    StateTarget(
                        interface_id="test.set_gain/v1",
                        property_id="gain",
                        value=StateValue(2.0),
                    ),
                ),
            ),
        ),
        resource_order=("source-a", "source-b"),
        resource_requirements=_requirements("source-a", "source-b"),
    )
    engine = RunEffectInterpreter(
        run_id="conflicting-applied-state-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        instruments=TestRunInstrumentHost((first, second)),
        journal=FakeExecutionJournal(),
    )

    result = engine.run(complete_coverage_operations(program), points=program.points)

    assert result.indeterminate
    assert [problem.code for problem in result.problems] == [
        "instrument_driver_applied_with_error",
    ]
    assert len(first.applied) == 1
    assert second.applied == []
    assert result.final_state[0] != result.prepared_state[0]
    assert next(
        item.value
        for item in result.final_state[0].properties
        if item.interface_id == "test.set_gain/v1" and item.property_id == "gain"
    ) == StateValue(1.0)


def _gain_operation(instrument_id: str, value: float) -> ApplyStateOperation:
    return ApplyStateOperation(
        operation_id=f"blocking-state-point.state.{instrument_id}",
        instrument_id=instrument_id,
        targets=(
            StateTarget(
                interface_id="test.set_gain/v1",
                property_id="gain",
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
            command_id=operation_id,
            instrument_id=instrument_id,
            point_index=0,
            point_count=1,
            requests=[
                CollectResultRequest(
                    id="signal",
                    interface_id="test.scalar_signal/v1",
                    acquisition_id="sample",
                    result_id="signal",
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                request_id="signal",
                product_use_ids=(use.id,),
            ),
        ),
    )


def _collection_product_use(output_id: str) -> ProductUse:
    return ProductUse(
        product_id=product_id("signal"),
        id=ProductUseId(f"record:{output_id}"),
    )
