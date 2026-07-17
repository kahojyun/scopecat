from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.adapters.memory import MemoryExecutionJournal
from scopecat.adapters.memory.execution import MemoryMeasurementRecordCommitter
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.relations.model import literal_rows
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    DomainProgramId,
    DomainResultPortDef,
    MeasurementTransformId,
)
from scopecat.compiler.semantic.value_expressions import verify_table_value_expr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import (
    DomainProductProducer,
    MeasurementTransformProductProducer,
)
from scopecat.compiler.typed.program import (
    TypedDomainExecution,
    TypedDomainProgram,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    TypedProgram,
    product_output,
    record_product,
    shot_axis,
)
from scopecat.config.profiles import load_config_profile
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.kernel.product_identity import product_producer_id, product_use
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar, Table, TableColumn
from scopecat.measurements.projection import (
    bind_measurement_projection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.recording import commit_projected_measurement_records
from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainBatchContext,
    DomainHostTransformBinding,
    DomainHostTransformCall,
    DomainHostTransformImplementation,
    DomainMeasurementPlan,
    DomainPointRef,
    DomainProductUseRef,
    PreparedDomainExecution,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    project_domain_plan,
)
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    BinaryIqDiscriminator,
    CalibrationCatalog,
    CalibrationId,
    CircuitOperationId,
    CompiledQuantumTarget,
    Constant,
    IqCentroid,
    Measure,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    Play,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QuantumProgramId,
    QuantumProgramIR,
    QuantumTargetAcquisitionUseBinding,
    QuantumTargetEntryPointBinding,
    QubitId,
    ReadoutSignal,
    TargetAcquisitionAddress,
    TargetCompileEntryId,
    TargetCompilerId,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
    compile_target,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    seal_quantum_target_result_mapping,
    verify_quantum_program,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    FakeListTargetCompiler,
    default_fake_list_target,
    fake_measurement_invocation_spec,
    integrated_iq_shots,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)

from .demo_lab_experiment_testkit import link_program

_REPO_ROOT = Path(__file__).resolve().parents[5]
_Q0 = QubitId("q0")
_IQ_SLOT = AcquisitionSlotId("iq-result", scope=("circuit-local",))
_SHOT_COUNT = 5


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    context: DomainBatchContext
    prepared: PreparedDomainExecution
    measurements: DomainMeasurementPlan[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]
    runtime: FakeListDomainRuntime
    iq_use: DomainProductUseRef
    probability_0_use: DomainProductUseRef
    probability_1_use: DomainProductUseRef


def _linked_points() -> MaterializedLinkedPoints:
    point_type = Table(
        columns=(TableColumn("coordinate", Scalar(Float())),),
        min_rows=3,
        max_rows=3,
    )
    point_domain = PointDomain(
        root=point_rows(
            verify_table_value_expr(
                literal_rows(
                    (
                        {"coordinate": 10.0},
                        {"coordinate": 20.0},
                        {"coordinate": 30.0},
                    )
                ),
                bindings=RelationTypeBindings(),
                expected_type=point_type,
            )
        )
    )
    iq_shots = product_output(
        "integrated_iq_shots",
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(_SHOT_COUNT),),
    )
    probability_0 = product_output(
        "probability_0",
        dtype="float64",
        unit="ratio",
    )
    probability_1 = product_output(
        "probability_1",
        dtype="float64",
        unit="ratio",
    )
    iq_use = product_use(iq_shots.id)
    probability_0_use, probability_0_record = record_product(probability_0)
    probability_1_use, probability_1_record = record_product(probability_1)
    domain_program_id = DomainProgramId(SymbolId(local_id="binary-iq-program"))
    authored_transform = binary_iq_probability_transform(
        "binary-iq-discrimination",
        iq_shots="integrated_iq_shots",
        probability_0="probability_0",
        probability_1="probability_1",
        discriminator=BinaryIqDiscriminator(
            state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
            state_1_centroid=IqCentroid(real=1.0, imag=0.0),
            tie_policy="state_0",
        ),
    )
    transform_id = MeasurementTransformId(SymbolId(local_id=authored_transform.id))
    iq_producer_id = product_producer_id("iq-shots-producer")
    probability_0_producer_id = product_producer_id("probability-0-producer")
    probability_1_producer_id = product_producer_id("probability-1-producer")
    program = TypedProgram(
        id="fake-host-transform-e2e",
        kind="fake_host_transform_e2e",
        point_domain=point_domain,
        product_defs=(iq_shots, probability_0, probability_1),
        domain_execution=TypedDomainExecution(
            program=TypedDomainProgram(
                id=domain_program_id,
                dialect_id="test.quantum.host-transform",
                dialect_version="1",
                body=("binary-iq-readout", "v1"),
                result_ports=(DomainResultPortDef("iq_shots"),),
            ),
            results=(
                TypedDomainResultBinding(
                    id="iq_shots",
                    product_id=iq_shots.id,
                    producer_id=iq_producer_id,
                    product_use_ids=(iq_use.id,),
                ),
            ),
        ),
        measurement_transforms=(
            TypedMeasurementTransform(
                id=transform_id,
                semantic=authored_transform.semantic,
                rate="point",
                inputs=(
                    TypedMeasurementTransformInput(
                        id="iq_shots",
                        product_id=iq_shots.id,
                        product_use_id=iq_use.id,
                    ),
                ),
                outputs=(
                    TypedMeasurementTransformOutput(
                        id="probability_0",
                        product_id=probability_0.id,
                        producer_id=probability_0_producer_id,
                        product_use_ids=(probability_0_use.id,),
                    ),
                    TypedMeasurementTransformOutput(
                        id="probability_1",
                        product_id=probability_1.id,
                        producer_id=probability_1_producer_id,
                        product_use_ids=(probability_1_use.id,),
                    ),
                ),
            ),
        ),
        domain_product_producers=(
            DomainProductProducer(
                id=iq_producer_id,
                product_id=iq_shots.id,
                result_id="iq_shots",
            ),
        ),
        measurement_transform_product_producers=(
            MeasurementTransformProductProducer(
                id=probability_0_producer_id,
                product_id=probability_0.id,
                transform_id=transform_id,
                output_id="probability_0",
            ),
            MeasurementTransformProductProducer(
                id=probability_1_producer_id,
                product_id=probability_1.id,
                transform_id=transform_id,
                output_id="probability_1",
            ),
        ),
        product_uses=(iq_use, probability_0_use, probability_1_use),
        record_uses=(
            probability_0_record,
            probability_1_record,
            replace(probability_1_record, id="probability_1_alias"),
        ),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _lowered_measurement_program():
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=_Q0,
        acquisition_slot_id=_IQ_SLOT,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    program = verify_quantum_program(
        QuantumProgramIR(
            id=QuantumProgramId("binary-iq-readout"),
            body=measurement,
        ),
        (),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-iq-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(_Q0),
    )
    template = PulseProgram(
        id=PulseProgramId("binary-iq-readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(_Q0),
                    envelope=Constant(
                        duration=Quantity(4, "ns"),
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=AcquireSignal(_Q0),
                    slot_id=template_slot.id,
                    duration=Quantity(4, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    calibration = MeasurementCalibration(
        id=CalibrationId("binary-iq-readout-q0"),
        key=MeasurementCalibrationKey.from_measurement(measurement),
        pulse_template=template,
    )
    return lower_quantum_program_to_pulses(
        program,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
        output_id=PulseProgramId("binary-iq-readout-pulses"),
    )


def _scenario(
    host_implementation: DomainHostTransformImplementation,
) -> _Scenario:
    linked_points = _linked_points()
    projection = project_domain_plan(linked_points)
    view = projection.view(linked_points)
    execution = view.require_execution(dialect_id="test.quantum.host-transform")
    iq_use = execution.result("iq_shots").require_one_product_use()
    [transform] = execution.measurement_transforms
    [probability_0_use] = transform.output("probability_0").product_uses
    [probability_1_use] = transform.output("probability_1").product_uses
    assert all(
        isinstance(product_use, DomainProductUseRef)
        for product_use in (iq_use, probability_0_use, probability_1_use)
    )
    context = make_domain_batch_context(
        projection,
        MaterializedLinkedPointBatch(linked_points, (0, 1, 2)),
        adapter_id="test.fake-host-transform",
        batch_ordinal=0,
    )
    assert all(isinstance(point, DomainPointRef) for point in context.points)
    assert context.direct_product_uses == (iq_use,)
    assert context.product_uses == (
        iq_use,
        probability_0_use,
        probability_1_use,
    )
    preparation = context.new_preparation()

    lowered = _lowered_measurement_program()
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_quantum_target_entry(
            TargetCompileEntryId(f"binary-iq-entry-{point_index}"),
            lowered,
        )
        for point_index in adapter_point_order
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    target_batch = prepare_quantum_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=_SHOT_COUNT,
    )
    mapping = seal_quantum_target_result_mapping(
        preparation,
        target_batch,
        tuple(
            QuantumTargetEntryPointBinding(
                entry.id,
                context.points[point_index],
            )
            for entry, point_index in zip(
                target_batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            QuantumTargetAcquisitionUseBinding(
                entry.acquisition_addresses[0],
                iq_use,
            )
            for entry in target_batch.entries
        ),
    )
    compiled_target = CompiledQuantumTarget(
        mapping,
        compile_target(compiler, target_batch.request),
    )
    realization = select_fake_measurement_realization(
        compiled_target,
        target,
        tuple(
            integrated_iq_shots(result.result_address)
            for result in mapping.domain_mapping.results
        ),
    )
    invocation = fake_measurement_invocation_spec(
        realization,
        invocation_id="binary-iq-readout",
    )
    measurements = preparation.measurement_plan(
        mapping.domain_mapping,
        host_transforms=(DomainHostTransformBinding(transform, host_implementation),),
    )
    runtime = FakeListDomainRuntime()

    def realize(
        fetched: CorrelatedDomainFetch[FakeListRun],
    ):
        return realize_fetched_fake_measurements(realization, fetched).result_values

    prepared = preparation.build(
        measurements=measurements,
        invocation=invocation,
        runtime=runtime,
        realize=realize,
    )
    return _Scenario(
        linked_points=linked_points,
        context=context,
        prepared=prepared,
        measurements=measurements,
        runtime=runtime,
        iq_use=iq_use,
        probability_0_use=probability_0_use,
        probability_1_use=probability_1_use,
    )


def test_fake_domain_iq_reaches_host_probabilities_and_durable_records() -> None:
    reference = binary_iq_probability_host_implementation()
    kernel_calls: list[DomainHostTransformCall] = []

    def counted_kernel(call: DomainHostTransformCall):
        kernel_calls.append(call)
        return reference.kernel(call)

    counted_implementation = replace(reference, kernel=counted_kernel)
    scenario = _scenario(counted_implementation)
    value_selection = scenario.prepared.source_fragment.selection
    projection = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        value_selection,
    )
    journal = MemoryExecutionJournal()
    committer = MemoryMeasurementRecordCommitter()
    run_id = "fake-host-transform-run"
    executed = execute_domain_job_values(
        scenario.prepared,
        run_id="fake-host-transform-run",
        journal=journal,
    )
    projected = project_measurement_records(
        projection,
        executed,
        run_id=run_id,
    )
    committed = commit_projected_measurement_records(
        projected,
        committer,
        journal,
    )

    measurements = scenario.measurements
    assert measurements.source_product_uses == (scenario.iq_use,)
    assert measurements.derived_product_uses == (
        scenario.probability_0_use,
        scenario.probability_1_use,
    )
    assert measurements.product_uses == (
        scenario.iq_use,
        scenario.probability_0_use,
        scenario.probability_1_use,
    )
    [host_binding] = measurements.host_transforms
    assert host_binding.implementation is counted_implementation
    assert tuple(port.product_use for port in host_binding.transform.inputs) == (
        scenario.iq_use,
    )
    assert tuple(port.product_uses for port in host_binding.transform.outputs) == (
        (scenario.probability_0_use,),
        (scenario.probability_1_use,),
    )
    assert tuple(
        product_use_id.value for product_use_id in executed.product_use_ids
    ) == (
        scenario.iq_use.id,
        scenario.probability_0_use.id,
        scenario.probability_1_use.id,
    )

    points = scenario.linked_points.point_domain.points
    assert scenario.runtime.physical_execution_count == 1
    assert [(call.point, call.point_index) for call in kernel_calls] == [
        (point, point.ordinal) for point in scenario.context.points
    ]
    assert all(
        tuple(port.id for port in call.input_ports) == ("iq_shots",)
        and {port.id for port in call.output_ports}
        == {"probability_0", "probability_1"}
        and "ports" not in call.semantic.parameters
        and call.semantic.portability == "host_only"
        for call in kernel_calls
    )
    assert len(projected.records) == len(points)
    assert len(committer.chunks) == len(points)
    assert len(committed.receipts) == len(points)
    assert all(
        set(record.observables)
        == {"probability_0", "probability_1", "probability_1_alias"}
        for record in projected.records
    )
    for record in projected.records:
        probability_0 = record.observables["probability_0"]
        probability_1 = record.observables["probability_1"]
        assert isinstance(probability_0, Quantity)
        assert isinstance(probability_1, Quantity)
        assert probability_0.unit == probability_1.unit == "ratio"
        assert probability_0.value + probability_1.value == pytest.approx(1.0)
        assert record.observables["probability_1_alias"] == probability_1

    forbidden_evidence_terms = (
        "entry_address",
        "result_address",
        "target_run",
        "raw_frame",
        "raw_frames",
    )
    assert all(
        all(term not in repr(transition.evidence) for term in forbidden_evidence_terms)
        for transition in journal.entries
    )
