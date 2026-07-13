"""Reference X-count experiment for the fake AWG and digitizer.

The caller owns Scopecat authoring and supplies an already materialized point
space plus the exact logical products selected by that authoring path.  This
module owns only laboratory composition: one calibrated circuit per X-count,
fake list-target compilation, domain submission, integrated-IQ realization,
host discrimination, and durable measurement-record commits.

Preparation is pure and closes every mapping before the first device effect.
The lab-owned domain adapter passes that proof to the standard
``Workspace.prepare(...).run()`` lifecycle; this module deliberately exposes no parallel
execution entrypoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from scopecat import Quantity
from scopecat.domain_invocation import MaterializedLinkedPoints, ProductUseId
from scopecat.measurement_projection import (
    BoundMeasurementProjection,
    bind_measurement_projection,
    select_measurement_projection,
)
from scopecat.measurement_transforms import (
    BoundHostMeasurementTransformPlan,
    HostMeasurementTransformFragmentBinding,
    HostMeasurementTransformImplementation,
    HostMeasurementTransformImplementationBinding,
    MeasurementTransformId,
    MeasurementTransformPort,
    ProductDef,
    bind_host_measurement_transforms,
    select_host_measurement_transforms,
    verify_measurement_transform_graph,
)
from scopecat.measurement_values import (
    BoundDomainMeasurementValueFragment,
    ProductValueFragmentDef,
    bind_domain_output_fragment,
    select_measurement_value_assembly,
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
    CircuitId,
    CircuitOperationId,
    CircuitProgram,
    CircuitSequence,
    CircuitTargetAcquisitionUseBinding,
    CircuitTargetEntryPointBinding,
    CompiledCircuitTarget,
    Constant,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateCall,
    GateDefinition,
    GateId,
    IqCentroid,
    Measure,
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
    Play,
    PreparedCircuitTargetEntry,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QubitId,
    ReadoutSignal,
    TargetCompileEntryId,
    TargetCompilerId,
    VerifiedCircuitProgram,
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
    FakeListArtifact,
    FakeListTarget,
    FakeListTargetCompiler,
    SelectedFakeMeasurementRealization,
    close_fake_measurement_invocation,
    default_fake_list_target,
    integrated_iq_shots,
    select_fake_measurement_realization,
)

DOMAIN_FRAGMENT_ID = "fake-x-count-domain-iq"
TRANSFORM_FRAGMENT_ID = "fake-x-count-binary-probabilities"
TRANSFORM_ID = MeasurementTransformId("fake-x-count-binary-iq")
DEFAULT_COMPILER_ID = TargetCompilerId("quantum-lab-demo.fake-x-count.v1")
DEFAULT_QUBIT = QubitId("q0")


@dataclass(frozen=True, slots=True)
class FakeXCountProductBinding:
    """Exact core product-use occurrences owned by this composition."""

    iq_shots: ProductUseId
    probability_0: ProductUseId
    probability_1: ProductUseId

    def __post_init__(self) -> None:
        selected = (self.iq_shots, self.probability_0, self.probability_1)
        if any(not isinstance(value, ProductUseId) for value in selected):
            msg = "fake X-count product bindings require ProductUseId values"
            raise TypeError(msg)
        if len(set(selected)) != len(selected):
            msg = "fake X-count IQ and probability product uses must be distinct"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PreparedFakeXCountReference:
    """Pure, completely bound fake-target and host-processing plan."""

    linked_points: MaterializedLinkedPoints = field(repr=False)
    products: FakeXCountProductBinding
    x_count_column: str
    x_counts: tuple[int, ...]
    target: FakeListTarget
    compiler: FakeListTargetCompiler
    calibration_catalog: CalibrationCatalog
    circuits: tuple[VerifiedCircuitProgram, ...]
    entries: tuple[PreparedCircuitTargetEntry, ...]
    compiled_target: CompiledCircuitTarget[FakeListArtifact]
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: ExecutableFakeMeasurementInvocation = field(repr=False)
    domain_fragment: BoundDomainMeasurementValueFragment = field(repr=False)
    transform_plan: BoundHostMeasurementTransformPlan = field(repr=False)
    projection: BoundMeasurementProjection = field(repr=False)

    @property
    def shots(self) -> int:
        """Return the number of hardware repetitions per list entry."""

        return self.compiled_target.compiled.repetitions


def prepare_fake_x_count_reference(
    linked_points: MaterializedLinkedPoints,
    products: FakeXCountProductBinding,
    *,
    x_count_column: str = "x_count",
    shots: int = 32,
    qubit: QubitId = DEFAULT_QUBIT,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = DEFAULT_COMPILER_ID,
    discriminator: BinaryIqDiscriminator | None = None,
    host_implementation: HostMeasurementTransformImplementation | None = None,
    invocation_id: str = "fake-x-count",
) -> PreparedFakeXCountReference:
    """Close the reference circuit, target, result, and transform mappings.

    ``x_count_column`` must contain a non-negative integer in every logical
    point.  Point order becomes hardware list order, while result mapping keeps
    the canonical logical point identities explicit.
    """

    if not isinstance(linked_points, MaterializedLinkedPoints):
        msg = "fake X-count preparation requires MaterializedLinkedPoints"
        raise TypeError(msg)
    if not isinstance(products, FakeXCountProductBinding):
        msg = "fake X-count preparation requires a product binding"
        raise TypeError(msg)
    if not isinstance(x_count_column, str) or not x_count_column:
        msg = "fake X-count column must be a non-empty string"
        raise ValueError(msg)
    if type(shots) is not int or shots <= 0:
        msg = "fake X-count shots must be a positive integer"
        raise ValueError(msg)
    if not isinstance(qubit, QubitId):
        msg = "fake X-count qubit must be a QubitId"
        raise TypeError(msg)
    selected_target = default_fake_list_target() if target is None else target
    if not isinstance(selected_target, FakeListTarget):
        msg = "fake X-count target must be a FakeListTarget"
        raise TypeError(msg)
    if not isinstance(compiler_id, TargetCompilerId):
        msg = "fake X-count compiler_id must be a TargetCompilerId"
        raise TypeError(msg)
    if not invocation_id:
        msg = "fake X-count invocation_id must be non-empty"
        raise ValueError(msg)

    x_counts = _x_counts(linked_points, x_count_column)
    product_contracts = _product_contracts(linked_points, products)
    _require_probability_records(linked_points, products)

    gate = GateDefinition(GateId("x"), qubit_arity=1)
    catalog = _calibration_catalog(qubit, gate)
    circuits = tuple(
        _x_count_circuit(
            qubit=qubit,
            gate=gate,
            x_count=x_count,
            point_index=point_index,
        )
        for point_index, x_count in enumerate(x_counts)
    )
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(f"fake-x-count-entry-{point_index}"),
            circuit,
            select_calibrations(circuit, catalog),
            output_id=PulseProgramId(f"fake-x-count-pulses-{point_index}"),
        )
        for point_index, circuit in enumerate(circuits)
    )
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_circuit_target_batch(
        entries,
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    points = linked_points.point_domain.points
    mapping = seal_circuit_target_result_mapping(
        linked_points,
        batch,
        tuple(
            CircuitTargetEntryPointBinding(entry.id, point.logical_id)
            for entry, point in zip(entries, points, strict=True)
        ),
        tuple(
            CircuitTargetAcquisitionUseBinding(
                entry.acquisition_addresses[0],
                products.iq_shots,
            )
            for entry in entries
        ),
    )
    compiled_target = bind_compiled_circuit_target(
        mapping,
        compile_target(compiler, batch.request),
    )
    realization = select_fake_measurement_realization(
        compiled_target,
        selected_target,
        tuple(integrated_iq_shots(result.result_address) for result in mapping.results),
    )
    invocation = close_fake_measurement_invocation(
        realization,
        invocation_id=invocation_id,
    )

    value_selection = select_measurement_value_assembly(
        linked_points,
        required_product_use_ids=(
            products.iq_shots,
            products.probability_0,
            products.probability_1,
        ),
        fragment_defs=(
            ProductValueFragmentDef(DOMAIN_FRAGMENT_ID, (products.iq_shots,)),
            ProductValueFragmentDef(
                TRANSFORM_FRAGMENT_ID,
                (products.probability_0, products.probability_1),
            ),
        ),
    )
    domain_fragment = bind_domain_output_fragment(
        value_selection,
        DOMAIN_FRAGMENT_ID,
        invocation.payload.core_outputs,
    )
    transform = binary_iq_probability_transform(
        TRANSFORM_ID,
        iq_shots=MeasurementTransformPort(
            "iq_shots",
            products.iq_shots,
            product_contracts[0],
        ),
        probability_0=MeasurementTransformPort(
            "probability_0",
            products.probability_0,
            product_contracts[1],
        ),
        probability_1=MeasurementTransformPort(
            "probability_1",
            products.probability_1,
            product_contracts[2],
        ),
        discriminator=(
            _default_discriminator() if discriminator is None else discriminator
        ),
    )
    graph = verify_measurement_transform_graph(linked_points, (transform,))
    implementation = (
        binary_iq_probability_host_implementation()
        if host_implementation is None
        else host_implementation
    )
    host_selection = select_host_measurement_transforms(
        graph,
        (implementation,),
        (
            HostMeasurementTransformImplementationBinding(
                transform.id,
                implementation.id,
            ),
        ),
    )
    transform_plan = bind_host_measurement_transforms(
        host_selection,
        value_selection,
        (
            HostMeasurementTransformFragmentBinding(
                transform.id,
                TRANSFORM_FRAGMENT_ID,
            ),
        ),
    )
    owned_product_use_ids = {
        products.iq_shots,
        products.probability_0,
        products.probability_1,
    }
    projection = bind_measurement_projection(
        select_measurement_projection(
            linked_points,
            record_ids=tuple(
                record.id
                for record in linked_points.linked_plan.record_uses
                if record.product_use_id in owned_product_use_ids
            ),
        ),
        value_selection,
    )
    return PreparedFakeXCountReference(
        linked_points=linked_points,
        products=products,
        x_count_column=x_count_column,
        x_counts=x_counts,
        target=selected_target,
        compiler=compiler,
        calibration_catalog=catalog,
        circuits=circuits,
        entries=entries,
        compiled_target=compiled_target,
        realization=realization,
        invocation=invocation,
        domain_fragment=domain_fragment,
        transform_plan=transform_plan,
        projection=projection,
    )


def _x_counts(
    linked_points: MaterializedLinkedPoints,
    column: str,
) -> tuple[int, ...]:
    points = linked_points.point_domain.points
    if not points:
        msg = "fake X-count experiments require at least one logical point"
        raise ValueError(msg)
    counts: list[int] = []
    for point in points:
        row = point.row
        if column not in row:
            msg = f"fake X-count point {point.logical_ordinal} has no {column!r} value"
            raise ValueError(msg)
        value = row[column]
        if type(value) is not int or value < 0:
            msg = (
                f"fake X-count point {point.logical_ordinal} requires a "
                f"non-negative integer {column!r} value"
            )
            raise ValueError(msg)
        counts.append(value)
    return tuple(counts)


def _product_contracts(
    linked_points: MaterializedLinkedPoints,
    products: FakeXCountProductBinding,
) -> tuple[ProductDef, ProductDef, ProductDef]:
    plan = linked_points.linked_plan
    uses_by_id = {use.id: use for use in plan.product_uses}
    definitions_by_id = {product.id: product for product in plan.product_defs}
    selected_ids = (products.iq_shots, products.probability_0, products.probability_1)
    unknown = tuple(use_id for use_id in selected_ids if use_id not in uses_by_id)
    if unknown:
        rendered = ", ".join(repr(use_id.value) for use_id in unknown)
        msg = f"fake X-count product uses are not in the linked plan: {rendered}"
        raise ValueError(msg)
    selected = tuple(
        definitions_by_id[uses_by_id[use_id].product_id] for use_id in selected_ids
    )
    return cast("tuple[ProductDef, ProductDef, ProductDef]", selected)


def _require_probability_records(
    linked_points: MaterializedLinkedPoints,
    products: FakeXCountProductBinding,
) -> None:
    recorded = {
        record.product_use_id for record in linked_points.linked_plan.record_uses
    }
    missing = {
        products.probability_0,
        products.probability_1,
    } - recorded
    if missing:
        msg = "fake X-count probability products must both have record selections"
        raise ValueError(msg)


def _calibration_catalog(
    qubit: QubitId,
    gate: GateDefinition,
) -> CalibrationCatalog:
    x_template = PulseProgram(
        id=PulseProgramId("fake-x-count-x-template"),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=Constant(
                duration=Quantity(4, "ns"),
                amplitude=Quantity(0.25, "arb"),
            ),
        ),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-iq-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(qubit),
    )
    readout_template = PulseProgram(
        id=PulseProgramId("fake-x-count-readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("stimulus"),
                    signal=ReadoutSignal(qubit),
                    envelope=Constant(
                        duration=Quantity(8, "ns"),
                        amplitude=Quantity(0.4, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("capture"),
                    signal=AcquireSignal(qubit),
                    slot_id=template_slot.id,
                    duration=Quantity(8, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=CalibrationId("fake-x-count-x-q0"),
                    key=GateCalibrationKey(gate.id, (qubit,)),
                    pulse_template=x_template,
                ),
            )
        ),
        measurements=MeasurementCalibrationCatalog(
            (
                MeasurementCalibration(
                    id=CalibrationId("fake-x-count-readout-q0"),
                    key=MeasurementCalibrationKey(
                        qubit,
                        AcquisitionKind.INTEGRATED_IQ,
                    ),
                    pulse_template=readout_template,
                ),
            )
        ),
    )


def _x_count_circuit(
    *,
    qubit: QubitId,
    gate: GateDefinition,
    x_count: int,
    point_index: int,
) -> VerifiedCircuitProgram:
    calls = tuple(
        GateCall(
            id=CircuitOperationId(f"x-{call_index}"),
            gate_id=gate.id,
            qubits=(qubit,),
        )
        for call_index in range(x_count)
    )
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=qubit,
        acquisition_slot_id=AcquisitionSlotId(
            "iq-result",
            scope=("fake-x-count",),
        ),
        acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
    )
    return verify_circuit_program(
        CircuitProgram(
            id=CircuitId(f"fake-x-count-point-{point_index}-x-{x_count}"),
            body=CircuitSequence((*calls, measurement)),
        ),
        (gate,),
    )


def _default_discriminator() -> BinaryIqDiscriminator:
    return BinaryIqDiscriminator(
        state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
        state_1_centroid=IqCentroid(real=1.0, imag=0.0),
        tie_policy="state_0",
    )


__all__ = [
    "DEFAULT_COMPILER_ID",
    "DEFAULT_QUBIT",
    "DOMAIN_FRAGMENT_ID",
    "TRANSFORM_FRAGMENT_ID",
    "TRANSFORM_ID",
    "FakeXCountProductBinding",
    "PreparedFakeXCountReference",
    "prepare_fake_x_count_reference",
]
