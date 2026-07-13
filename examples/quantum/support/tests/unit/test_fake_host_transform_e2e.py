from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    TypedProgram,
    product_output,
    record_product,
    shot_axis,
)
from scopecat._point_domain_algebra import point_rows
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import literal_rows
from scopecat._value_expressions import verify_table_value_expr
from scopecat.config_profiles import load_config_profile
from scopecat.domain_invocation import (
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat.domain_runtime import (
    CorrelatedDomainFetch,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)
from scopecat.execution_journal import MemoryExecutionJournal
from scopecat.measurement_projection import (
    bind_measurement_projection,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurement_recording import (
    MemoryMeasurementRecordCommitter,
    commit_projected_measurement_records,
)
from scopecat.measurement_transforms import (
    HostMeasurementTransformCall,
    HostMeasurementTransformFragmentBinding,
    HostMeasurementTransformImplementationBinding,
    MeasurementTransformId,
    MeasurementTransformPort,
    bind_host_measurement_transforms,
    execute_host_measurement_transforms,
    select_host_measurement_transforms,
    verify_measurement_transform_graph,
)
from scopecat.measurement_values import (
    ProductValueFragmentDef,
    bind_domain_output_fragment,
    domain_output_fragment,
    select_measurement_value_assembly,
)
from scopecat.value_types import Float, Scalar, Table, TableColumn
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    BinaryIqDiscriminator,
    CalibrationCatalog,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    CircuitProgram,
    CircuitTargetAcquisitionUseBinding,
    CircuitTargetEntryPointBinding,
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
    QubitId,
    ReadoutSignal,
    TargetCompileEntryId,
    TargetCompilerId,
    binary_iq_probability_host_implementation,
    binary_iq_probability_transform,
    bind_compiled_circuit_target,
    compile_target,
    prepare_circuit_target_batch,
    prepare_circuit_target_entry,
    seal_circuit_target_result_mapping,
    select_calibrations,
    verify_circuit_program,
)

from quantum_lab_demo.targets.fake_list_mode import (
    ExecutableFakeMeasurementInvocation,
    FakeListDomainRuntime,
    FakeListTargetCompiler,
    close_fake_measurement_invocation,
    default_fake_list_target,
    integrated_iq_shots,
    realize_fetched_fake_measurements,
    select_fake_measurement_realization,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_Q0 = QubitId("q0")
_IQ_SLOT = AcquisitionSlotId("iq-result", scope=("circuit-local",))
_SHOT_COUNT = 5
_DOMAIN_FRAGMENT_ID = "fake-list-domain-iq"
_TRANSFORM_FRAGMENT_ID = "binary-iq-probabilities"


@dataclass(frozen=True, slots=True)
class _Scenario:
    linked_points: MaterializedLinkedPoints
    invocation: ExecutableFakeMeasurementInvocation


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
    iq_use, _unused_iq_record = record_product(iq_shots)
    probability_0_use, probability_0_record = record_product(probability_0)
    probability_1_use, probability_1_record = record_product(probability_1)
    program = TypedProgram(
        id="fake-host-transform-e2e",
        kind="fake_host_transform_e2e",
        point_domain=point_domain,
        product_defs=(iq_shots, probability_0, probability_1),
        product_uses=(iq_use, probability_0_use, probability_1_use),
        record_uses=(
            probability_0_record,
            probability_1_record,
            probability_1_record.model_copy(update={"id": "probability_1_alias"}),
        ),
    )
    environment = validate_config_environment(
        load_config_profile(
            _REPO_ROOT / "fixtures/core/simple_scan/config-profile.json"
        )
    )
    return materialize_linked_points(link_program(program, environment))


def _measurement_selection():
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=_Q0,
        acquisition_slot_id=_IQ_SLOT,
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    circuit = verify_circuit_program(
        CircuitProgram(
            id=CircuitId("binary-iq-readout"),
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
    return circuit, select_calibrations(
        circuit,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
    )


def _scenario() -> _Scenario:
    linked_points = _linked_points()
    circuit, calibration_selection = _measurement_selection()
    adapter_point_order = (2, 0, 1)
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(f"binary-iq-entry-{point_index}"),
            circuit,
            calibration_selection,
            output_id=PulseProgramId("binary-iq-readout-pulses"),
        )
        for point_index in adapter_point_order
    )
    target = default_fake_list_target()
    compiler = FakeListTargetCompiler(
        TargetCompilerId("fake-list-compiler.v1"),
        target,
    )
    batch = prepare_circuit_target_batch(
        entries,
        target_id=target.id,
        compiler_id=compiler.id,
        capability_fingerprint=target.capability_fingerprint,
        repetitions=_SHOT_COUNT,
    )
    points = linked_points.point_domain.points
    iq_use = linked_points.linked_plan.product_uses[0]
    mapping = seal_circuit_target_result_mapping(
        linked_points,
        batch,
        tuple(
            CircuitTargetEntryPointBinding(
                entry.id,
                points[point_index].logical_id,
            )
            for entry, point_index in zip(
                batch.entries,
                adapter_point_order,
                strict=True,
            )
        ),
        tuple(
            CircuitTargetAcquisitionUseBinding(
                entry.acquisition_addresses[0],
                iq_use.id,
            )
            for entry in batch.entries
        ),
    )
    compiled_target = bind_compiled_circuit_target(
        mapping,
        compile_target(compiler, batch.request),
    )
    realization = select_fake_measurement_realization(
        compiled_target,
        target,
        tuple(integrated_iq_shots(result.result_address) for result in mapping.results),
    )
    return _Scenario(
        linked_points=linked_points,
        invocation=close_fake_measurement_invocation(
            realization,
            invocation_id="binary-iq-readout",
        ),
    )


def test_fake_domain_iq_reaches_host_probabilities_and_durable_records() -> None:
    scenario = _scenario()
    iq_use, probability_0_use, probability_1_use = (
        scenario.linked_points.linked_plan.product_uses
    )
    iq_product, probability_0_product, probability_1_product = (
        scenario.linked_points.linked_plan.product_defs
    )
    value_selection = select_measurement_value_assembly(
        scenario.linked_points,
        required_product_use_ids=(
            iq_use.id,
            probability_0_use.id,
            probability_1_use.id,
        ),
        fragment_defs=(
            ProductValueFragmentDef(_DOMAIN_FRAGMENT_ID, (iq_use.id,)),
            ProductValueFragmentDef(
                _TRANSFORM_FRAGMENT_ID,
                (probability_0_use.id, probability_1_use.id),
            ),
        ),
    )
    domain_binding = bind_domain_output_fragment(
        value_selection,
        _DOMAIN_FRAGMENT_ID,
        scenario.invocation.payload.core_outputs,
    )
    transform = binary_iq_probability_transform(
        MeasurementTransformId("binary-iq-discrimination"),
        iq_shots=MeasurementTransformPort(
            "iq_shots",
            iq_use.id,
            iq_product,
        ),
        probability_0=MeasurementTransformPort(
            "probability_0",
            probability_0_use.id,
            probability_0_product,
        ),
        probability_1=MeasurementTransformPort(
            "probability_1",
            probability_1_use.id,
            probability_1_product,
        ),
        discriminator=BinaryIqDiscriminator(
            state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
            state_1_centroid=IqCentroid(real=1.0, imag=0.0),
            tie_policy="state_0",
        ),
    )
    graph = verify_measurement_transform_graph(
        scenario.linked_points,
        (transform,),
    )
    reference = binary_iq_probability_host_implementation()
    kernel_calls: list[HostMeasurementTransformCall] = []

    def counted_kernel(call: HostMeasurementTransformCall):
        kernel_calls.append(call)
        return reference.kernel(call)

    host_selection = select_host_measurement_transforms(
        graph,
        (replace(reference, kernel=counted_kernel),),
        (
            HostMeasurementTransformImplementationBinding(
                transform.id,
                reference.id,
            ),
        ),
    )
    transform_plan = bind_host_measurement_transforms(
        host_selection,
        value_selection,
        (
            HostMeasurementTransformFragmentBinding(
                transform.id,
                _TRANSFORM_FRAGMENT_ID,
            ),
        ),
    )
    projection = bind_measurement_projection(
        select_measurement_projection(scenario.linked_points),
        value_selection,
    )

    runtime = FakeListDomainRuntime()
    journal = MemoryExecutionJournal()
    committer = MemoryMeasurementRecordCommitter()
    submission_id = plan_domain_submission(
        scenario.invocation,
        run_id="fake-host-transform-run",
        semantic_operation_id="binary-iq-readout",
    )
    submission = submit_domain_invocation(
        runtime,
        scenario.invocation,
        submission_id,
        journal=journal,
    )
    fetched = fetch_domain_invocation(
        runtime,
        scenario.invocation.intent,
        submission,
        journal=journal,
    )
    assert isinstance(fetched, CorrelatedDomainFetch)
    realized = realize_fetched_fake_measurements(scenario.invocation, fetched)
    domain_fragment = domain_output_fragment(domain_binding, realized.output_values)
    executed = execute_host_measurement_transforms(
        transform_plan,
        (domain_fragment,),
    )
    projected = project_measurement_records(
        projection,
        executed.values,
        run_id=submission_id.run_id,
    )
    committed = commit_projected_measurement_records(
        projected,
        committer,
        journal,
    )

    assert domain_binding.domain_outputs.mapping.selected_product_use_ids == (
        iq_use.id,
    )
    assert domain_fragment.fragment_id == _DOMAIN_FRAGMENT_ID
    assert domain_fragment.selection.fragment(_DOMAIN_FRAGMENT_ID).product_use_ids == (
        iq_use.id,
    )
    assert tuple(fragment.fragment_id for fragment in executed.transform_fragments) == (
        _TRANSFORM_FRAGMENT_ID,
    )
    assert executed.transform_fragments[0].selection.fragment(
        _TRANSFORM_FRAGMENT_ID
    ).product_use_ids == (probability_0_use.id, probability_1_use.id)
    assert executed.values.product_use_ids == (
        iq_use.id,
        probability_0_use.id,
        probability_1_use.id,
    )

    points = scenario.linked_points.point_domain.points
    assert runtime.physical_execution_count == 1
    assert [(call.logical_point_id, call.point_index) for call in kernel_calls] == [
        (point.logical_id, point.logical_ordinal) for point in points
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
