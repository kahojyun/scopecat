"""Reference X-count experiment for the fake AWG and digitizer.

The caller owns Scopecat authoring and supplies a context-bound preparation
builder plus exact SDK product-use references. This module owns laboratory
composition: one calibrated circuit per X-count, fake list-target compilation,
domain submission, integrated-IQ realization, host discrimination, and durable
measurement-record commits.

Preparation is pure and closes every mapping before the first device effect.
The lab-owned domain adapter passes that proof to the standard
``Workspace.prepare(...).run()`` lifecycle; this module deliberately exposes no parallel
execution entrypoint.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from scopecat import Quantity
from scopecat.sdk.domain.measurements import (
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
)
from scopecat.sdk.domain.preparation import (
    DomainMeasurementPlan,
    DomainPreparationBuilder,
)
from scopecat.sdk.domain.view import (
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductUseRef,
)
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CircuitTargetAcquisitionUseBinding,
    CircuitTargetEntryPointBinding,
    CompiledCircuitTarget,
    Constant,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateDefinition,
    GateId,
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
    TargetAcquisitionAddress,
    TargetCompileEntryId,
    TargetCompilerId,
    VerifiedCircuitProgram,
    binary_iq_probability_host_implementation,
    bind_compiled_circuit_target,
    compile_target,
    prepare_circuit_target_batch,
    prepare_circuit_target_entry,
    seal_circuit_target_result_mapping,
    select_calibrations,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeListArtifact,
    FakeListTarget,
    FakeListTargetCompiler,
    FakeMeasurementInvocationSpec,
    SelectedFakeMeasurementRealization,
    default_fake_list_target,
    fake_measurement_invocation_spec,
    integrated_iq_shots,
    select_fake_measurement_realization,
)

DEFAULT_COMPILER_ID = TargetCompilerId("quantum-lab-demo.fake-x-count.v1")
DEFAULT_QUBIT = QubitId("q0")


@dataclass(frozen=True, slots=True)
class FakeXCountProductBinding:
    """Context-owned direct IQ uses and authored host transform."""

    iq_shots: tuple[DomainProductUseRef, ...]
    transform: DomainMeasurementTransform

    def __post_init__(self) -> None:
        selected = tuple(self.iq_shots)
        if not selected:
            msg = "fake X-count product bindings require at least one IQ use"
            raise ValueError(msg)
        if any(not isinstance(value, DomainProductUseRef) for value in selected):
            msg = "fake X-count product bindings require SDK product-use references"
            raise TypeError(msg)
        if len(set(selected)) != len(selected):
            msg = "fake X-count IQ product uses must be distinct"
            raise ValueError(msg)
        if not isinstance(self.transform, DomainMeasurementTransform):
            msg = "fake X-count product bindings require an authored transform"
            raise TypeError(msg)
        object.__setattr__(self, "iq_shots", selected)


@dataclass(frozen=True, slots=True)
class PreparedFakeXCountReference:
    """Pure, completely bound fake-target and host-processing plan."""

    preparation: DomainPreparationBuilder = field(repr=False)
    products: FakeXCountProductBinding
    x_counts: tuple[int, ...]
    target: FakeListTarget
    compiler: FakeListTargetCompiler
    calibration_catalog: CalibrationCatalog
    circuits: tuple[VerifiedCircuitProgram, ...]
    entries: tuple[PreparedCircuitTargetEntry, ...]
    compiled_target: CompiledCircuitTarget[FakeListArtifact]
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: FakeMeasurementInvocationSpec = field(repr=False)
    measurements: DomainMeasurementPlan[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ] = field(repr=False)

    @property
    def shots(self) -> int:
        """Return the number of hardware repetitions per list entry."""

        return self.compiled_target.compiled.repetitions


def prepare_fake_x_count_reference(
    preparation: DomainPreparationBuilder,
    products: FakeXCountProductBinding,
    *,
    acquisition_slot_id: AcquisitionSlotId,
    circuits: Sequence[VerifiedCircuitProgram],
    x_counts: Sequence[int],
    shots: int = 32,
    qubit: QubitId = DEFAULT_QUBIT,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = DEFAULT_COMPILER_ID,
    host_implementation: DomainHostTransformImplementation | None = None,
    invocation_id: str = "fake-x-count",
) -> PreparedFakeXCountReference:
    """Close the reference circuit, target, result, and transform mappings.

    ``x_counts`` is supplied by the lab adapter's already bound point view.
    Its order must exactly match the canonical logical points; this target
    preparation no longer discovers authoring coordinates by a string name.
    """

    if not isinstance(preparation, DomainPreparationBuilder):
        msg = "fake X-count preparation requires a domain preparation builder"
        raise TypeError(msg)
    if not isinstance(products, FakeXCountProductBinding):
        msg = "fake X-count preparation requires a product binding"
        raise TypeError(msg)
    if not isinstance(acquisition_slot_id, AcquisitionSlotId):
        msg = "fake X-count preparation requires a typed acquisition slot"
        raise TypeError(msg)
    selected_circuits = tuple(circuits)
    if any(
        not isinstance(circuit, VerifiedCircuitProgram) for circuit in selected_circuits
    ):
        msg = "fake X-count preparation requires verified authored circuits"
        raise TypeError(msg)
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

    points = preparation.context.points
    selected_x_counts = _validated_x_counts(points, x_counts)
    if len(selected_circuits) != len(selected_x_counts):
        msg = "fake X-count circuits must exactly cover the logical point batch"
        raise ValueError(msg)
    if not selected_circuits:
        msg = "fake X-count preparation requires at least one authored circuit"
        raise ValueError(msg)
    gate = selected_circuits[0].gate_definition(GateId("x"))
    catalog = _calibration_catalog(qubit, gate)
    entries = tuple(
        prepare_circuit_target_entry(
            TargetCompileEntryId(f"fake-x-count-entry-{point.ordinal}"),
            circuit,
            select_calibrations(circuit, catalog),
            output_id=PulseProgramId(f"fake-x-count-pulses-{point.ordinal}"),
        )
        for point, circuit in zip(points, selected_circuits, strict=True)
    )
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_circuit_target_batch(
        entries,
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    mapping = seal_circuit_target_result_mapping(
        preparation,
        batch,
        tuple(
            CircuitTargetEntryPointBinding(entry.id, point)
            for entry, point in zip(
                entries,
                preparation.context.points,
                strict=True,
            )
        ),
        tuple(
            CircuitTargetAcquisitionUseBinding(
                _acquisition_address(entry, acquisition_slot_id),
                product_use,
            )
            for entry in entries
            for product_use in products.iq_shots
        ),
    )
    compiled_target = bind_compiled_circuit_target(
        mapping,
        compile_target(compiler, batch.request),
    )
    realization = select_fake_measurement_realization(
        compiled_target,
        selected_target,
        tuple(
            integrated_iq_shots(result.result_address)
            for result in mapping.domain_mapping.results
        ),
    )
    invocation = fake_measurement_invocation_spec(
        realization,
        invocation_id=invocation_id,
    )
    implementation = (
        binary_iq_probability_host_implementation()
        if host_implementation is None
        else host_implementation
    )
    measurements = preparation.measurement_plan(
        mapping.domain_mapping,
        host_transforms=(
            DomainHostTransformBinding(products.transform, implementation),
        ),
    )
    return PreparedFakeXCountReference(
        preparation=preparation,
        products=products,
        x_counts=selected_x_counts,
        target=selected_target,
        compiler=compiler,
        calibration_catalog=catalog,
        circuits=selected_circuits,
        entries=entries,
        compiled_target=compiled_target,
        realization=realization,
        invocation=invocation,
        measurements=measurements,
    )


def _acquisition_address(
    entry: PreparedCircuitTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    selected = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    if len(selected) != 1:
        msg = (
            f"fake X-count entry {entry.id.value!r} requires exactly one "
            f"acquisition for circuit result {slot_id.value!r}"
        )
        raise ValueError(msg)
    return selected[0]


def _validated_x_counts(
    points: Sequence[DomainPointRef],
    values: Sequence[int],
) -> tuple[int, ...]:
    selected_points = tuple(points)
    if not selected_points:
        msg = "fake X-count experiments require at least one logical point"
        raise ValueError(msg)
    counts = tuple(values)
    if len(counts) != len(selected_points):
        msg = "fake X-count values must exactly cover the logical point batch"
        raise ValueError(msg)
    for point, value in zip(selected_points, counts, strict=True):
        if type(value) is not int or value < 0:
            msg = (
                f"fake X-count point {point.ordinal} requires a "
                "non-negative integer value"
            )
            raise ValueError(msg)
    return counts


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


__all__ = [
    "DEFAULT_COMPILER_ID",
    "DEFAULT_QUBIT",
    "FakeXCountProductBinding",
    "PreparedFakeXCountReference",
    "prepare_fake_x_count_reference",
]
