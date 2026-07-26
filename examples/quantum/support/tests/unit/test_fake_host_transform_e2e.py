from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.compiler.semantic.model import (
    MeasurementTransformId,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedDomainExecution,
    TypedDomainResultBinding,
    TypedMeasurementTransform,
    TypedMeasurementTransformInput,
    TypedMeasurementTransformOutput,
    core_domain_executions,
    record_product,
    shot_axis,
)
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import DomainProgramDef, DomainResultPort
from scopecat.execution.effects.domain import execute_domain_job_values
from scopecat.execution.measurement_recording import (
    append_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.product_identity import product_id, product_use
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.measurements.products import ProductDef
from scopecat.measurements.projection import (
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.values import seal_measurement_values
from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainBatchContext,
    DomainHostTransformBinding,
    DomainHostTransformCall,
    DomainHostTransformImplementation,
    DomainPointRef,
    DomainProductUseRef,
    PreparedDomainExecution,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_template,
)
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
    QuantumProgramId,
    QubitId,
    TargetCompileEntryId,
    TargetCompilerId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.measurement_transforms import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
)
from scopecat_quantum.program_results import (
    CompiledQuantumTarget,
    QuantumTargetEntryPointBinding,
    QuantumTargetResultUseBinding,
    seal_quantum_target_result_mapping,
)
from scopecat_quantum.program_targets import (
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
)
from scopecat_quantum.programs import (
    QuantumProgramIR,
    lower_quantum_program_to_pulses,
    verify_quantum_program,
)
from scopecat_quantum.pulse_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationKey,
    ResolvedPulseImplementations,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Play,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import (
    Parallel as PulseParallel,
)
from scopecat_quantum.targets import compile_target
from tests.testkit.runtime import (
    FakeExecutionJournal,
    FakeMeasurementDatasetRepository,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeListDomainRuntime,
    FakeListRun,
    FakeListTargetCompiler,
    configured_fake_list_target,
    fake_measurement_invocation_spec,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)
from quantum_lab_demo.virtual_lab.wiring import quantum_wiring_config_profile

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
    host_transforms: tuple[DomainHostTransformBinding, ...]
    runtime: FakeListDomainRuntime
    iq_use: DomainProductUseRef
    probability_0_use: DomainProductUseRef
    probability_1_use: DomainProductUseRef


def _linked_points() -> MaterializedLinkedPoints:
    point_domain = PointDomain(
        root=point_axis_values(
            "coordinate",
            Scalar(Float()),
            (10.0, 20.0, 30.0),
        )
    )
    iq_shots = ProductDef(
        id=product_id("integrated_iq_shots"),
        dtype="complex128",
        unit="ratio",
        axes=(shot_axis(_SHOT_COUNT),),
    )
    probability_0 = ProductDef(
        id=product_id("probability_0"),
        dtype="float64",
        unit="ratio",
    )
    probability_1 = ProductDef(
        id=product_id("probability_1"),
        dtype="float64",
        unit="ratio",
    )
    iq_use = product_use(iq_shots.id)
    probability_0_use, probability_0_record = record_product(probability_0)
    probability_1_use, probability_1_record = record_product(probability_1)
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
    program = CoreProgram(
        id="fake-host-transform-e2e",
        kind="fake_host_transform_e2e",
        point_domain=point_domain,
        product_defs=(iq_shots, probability_0, probability_1),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="binary-iq-program",
                    dialect_id="test.quantum.host-transform",
                    dialect_version="1",
                    body=("binary-iq-readout", "v1"),
                    result_ports=(DomainResultPort("iq_shots"),),
                ),
                results=(
                    TypedDomainResultBinding(
                        id="iq_shots",
                        product_id=iq_shots.id,
                        product_use_ids=(iq_use.id,),
                    ),
                ),
            ),
        ),
        measurement_transforms=(
            TypedMeasurementTransform(
                id=transform_id,
                semantic=authored_transform.semantic,
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
                        product_use_ids=(probability_0_use.id,),
                    ),
                    TypedMeasurementTransformOutput(
                        id="probability_1",
                        product_id=probability_1.id,
                        product_use_ids=(probability_1_use.id,),
                    ),
                ),
            ),
        ),
        product_uses=(iq_use, probability_0_use, probability_1_use),
        record_uses=(
            probability_0_record,
            probability_1_record,
            replace(probability_1_record, id="probability_1_alias"),
        ),
    )
    environment = build_config_environment(
        load_config_snapshot_document(
            _REPO_ROOT / "fixtures/core/simple_scan/config-snapshot.json"
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
    implementation = MeasurementPulseImplementation(
        id=PulseImplementationId("binary-iq-readout-q0"),
        key=MeasurementPulseImplementationKey.from_measurement(measurement),
        pulse_template=template,
    )
    return lower_quantum_program_to_pulses(
        program,
        ResolvedPulseImplementations(
            measurements=(implementation,),
        ),
        output_id=PulseProgramId("binary-iq-readout-pulses"),
    )


def _scenario(
    host_implementation: DomainHostTransformImplementation,
) -> _Scenario:
    linked_points = _linked_points()
    typed_execution = core_domain_executions(linked_points.linked_plan.program)[0]
    execution_id = typed_execution.id
    closure = domain_result_closure(linked_points.linked_plan.program, execution_id)
    point_ordinals = (0, 1, 2)
    request = make_domain_compile_template(
        linked_points.linked_plan,
        execution_id,
        closure,
    ).bind_coverage(
        (point_ordinals,),
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution_id,
            "program",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
        lambda input_ids, ordinals, max_points: linked_points.bind_domain_inputs(
            execution_id,
            "compiler",
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    context = make_domain_batch_context(
        request,
        linked_points,
        point_ordinals,
        batch_ordinal=0,
    )
    execution = context.execution
    iq_use = execution.result("iq_shots").require_one_product_use()
    [transform] = execution.measurement_transforms
    [probability_0_use] = transform.output("probability_0").product_uses
    [probability_1_use] = transform.output("probability_1").product_uses
    assert all(
        isinstance(product_use, DomainProductUseRef)
        for product_use in (iq_use, probability_0_use, probability_1_use)
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
    target = configured_fake_list_target(quantum_wiring_config_profile())
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
            QuantumTargetResultUseBinding(
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
    )
    invocation = fake_measurement_invocation_spec(
        realization,
        invocation_id="binary-iq-readout",
    )
    host_transforms = (DomainHostTransformBinding(transform, host_implementation),)
    runtime = FakeListDomainRuntime()

    def realize(
        fetched: CorrelatedDomainFetch[FakeListRun],
    ):
        return realize_fetched_fake_measurements(realization, fetched)

    prepared = preparation.build(
        mapping=mapping.domain_mapping,
        host_transforms=host_transforms,
        invocation=invocation,
        runtime=runtime,
        realize=realize,
    )
    return _Scenario(
        linked_points=linked_points,
        context=context,
        prepared=prepared,
        host_transforms=host_transforms,
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
    projection = select_measurement_projection(
        scenario.context.measurement_catalog,
        scenario.linked_points.linked_plan.program.record_uses,
    )
    journal = FakeExecutionJournal()
    committer = FakeMeasurementDatasetRepository()
    run_id = "fake-host-transform-run"
    executed = seal_measurement_values(
        scenario.context.measurement_catalog,
        execute_domain_job_values(
            scenario.prepared,
            semantic_operation_id="domain",
            run_id="fake-host-transform-run",
            journal=journal,
        ),
        points=scenario.context.run_points,
    )
    projected = project_measurement_records(
        projection,
        executed,
        run_id=run_id,
        points=scenario.context.run_points,
    )
    committed = append_measurement_dataset(
        projected,
        committer,
        journal,
    )
    assert committed is not None
    assert projected.schema is not None
    seal_measurement_dataset(
        run_id=run_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        point_count=len(projected.records),
        append_content_hashes=(committed.dataset_content_hash,),
        writer=committer,
        journal=journal,
    )

    assert scenario.context.direct_product_uses == (scenario.iq_use,)
    assert scenario.context.derived_product_uses == (
        scenario.probability_0_use,
        scenario.probability_1_use,
    )
    assert scenario.context.product_uses == (
        scenario.iq_use,
        scenario.probability_0_use,
        scenario.probability_1_use,
    )
    [host_binding] = scenario.host_transforms
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
    assert (
        sum(
            entry.stage == "domain_submit"
            and entry.effect == "acquisition"
            and entry.state == "started"
            for entry in journal.entries
        )
        == 1
    )
    assert len(kernel_calls) == 1
    assert kernel_calls[0].points == scenario.context.points
    assert all(
        tuple(port.id for port in call.input_ports) == ("iq_shots",)
        and {port.id for port in call.output_ports}
        == {"probability_0", "probability_1"}
        and "ports" not in call.semantic.parameters
        for call in kernel_calls
    )
    assert len(projected.records) == len(points)
    assert len(committer.appends) == 1
    assert committed.dataset_content_hash == committer.appends[0].content_hash
    assert len(committer.receipts) == 2
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
