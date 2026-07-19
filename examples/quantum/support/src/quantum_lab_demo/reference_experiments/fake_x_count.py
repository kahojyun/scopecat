"""Reference X-count experiment for the fake AWG and digitizer.

The caller owns Scopecat authoring and supplies a context-bound preparation
builder plus exact SDK product-use references. This module owns laboratory
composition: one calibrated program per X-count, fake list-target compilation,
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
from scopecat.sdk.domain import (
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultMapping,
)
from scopecat_quantum import (
    Acquire,
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlot,
    AcquisitionSlotId,
    CalibrationCatalog,
    CalibrationId,
    CompiledQuantumTarget,
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
    PreparedQuantumTargetEntry,
    PulseEventId,
    PulseParallel,
    PulseProgram,
    PulseProgramId,
    QuantumTargetAcquisitionUseBinding,
    QuantumTargetEntryPointBinding,
    QubitId,
    ReadoutSignal,
    TargetAcquisitionAddress,
    TargetCompileEntryId,
    TargetCompilerId,
    VerifiedQuantumProgram,
    binary_iq_probability_host_implementation,
    compile_target,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_batch,
    prepare_quantum_target_entry,
    seal_quantum_target_result_mapping,
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
        if len(set(selected)) != len(selected):
            msg = "fake X-count IQ product uses must be distinct"
            raise ValueError(msg)
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
    programs: tuple[VerifiedQuantumProgram, ...]
    entries: tuple[PreparedQuantumTargetEntry, ...]
    compiled_target: CompiledQuantumTarget[FakeListArtifact]
    realization: SelectedFakeMeasurementRealization = field(repr=False)
    invocation: FakeMeasurementInvocationSpec = field(repr=False)
    measurement_mapping: DomainResultMapping[TargetAcquisitionAddress] = field(
        repr=False
    )
    host_transforms: tuple[DomainHostTransformBinding, ...] = field(repr=False)

    @property
    def shots(self) -> int:
        """Return the number of hardware repetitions per list entry."""

        return self.compiled_target.compiled.repetitions


def prepare_fake_x_count_reference(
    preparation: DomainPreparationBuilder,
    products: FakeXCountProductBinding,
    *,
    acquisition_slot_id: AcquisitionSlotId,
    programs: Sequence[VerifiedQuantumProgram],
    x_counts: Sequence[int],
    shots: int = 32,
    qubit: QubitId = DEFAULT_QUBIT,
    target: FakeListTarget | None = None,
    compiler_id: TargetCompilerId = DEFAULT_COMPILER_ID,
    host_implementation: DomainHostTransformImplementation | None = None,
    invocation_id: str = "fake-x-count",
) -> PreparedFakeXCountReference:
    """Close the reference program, target, result, and transform mappings.

    ``x_counts`` is supplied by the lab adapter's already bound point view.
    Its order must exactly match the canonical logical points; this target
    preparation no longer discovers authoring coordinates by a string name.
    """

    selected_programs = tuple(programs)
    if isinstance(shots, bool) or shots <= 0:
        msg = "fake X-count shots must be a positive integer"
        raise ValueError(msg)
    selected_target = default_fake_list_target() if target is None else target
    if not invocation_id:
        msg = "fake X-count invocation_id must be non-empty"
        raise ValueError(msg)

    points = preparation.context.points
    selected_x_counts = _validated_x_counts(points, x_counts)
    if len(selected_programs) != len(selected_x_counts):
        msg = "fake X-count programs must exactly cover the logical point batch"
        raise ValueError(msg)
    if not selected_programs:
        msg = "fake X-count preparation requires at least one authored program"
        raise ValueError(msg)
    gate = selected_programs[0].logical_circuit.gate_definition(GateId("x"))
    catalog = _calibration_catalog(qubit, gate)
    entries = tuple(
        prepare_quantum_target_entry(
            TargetCompileEntryId(f"fake-x-count-entry-{point.ordinal}"),
            lower_quantum_program_to_pulses(
                program,
                catalog,
                output_id=PulseProgramId(f"fake-x-count-pulses-{point.ordinal}"),
            ),
        )
        for point, program in zip(points, selected_programs, strict=True)
    )
    compiler = FakeListTargetCompiler(compiler_id, selected_target)
    batch = prepare_quantum_target_batch(
        entries,
        target_id=selected_target.id,
        compiler_id=compiler.id,
        capability_fingerprint=selected_target.capability_fingerprint,
        repetitions=shots,
    )
    mapping = seal_quantum_target_result_mapping(
        preparation,
        batch,
        tuple(
            QuantumTargetEntryPointBinding(entry.id, point)
            for entry, point in zip(
                entries,
                preparation.context.points,
                strict=True,
            )
        ),
        tuple(
            QuantumTargetAcquisitionUseBinding(
                _acquisition_address(entry, acquisition_slot_id),
                product_use,
            )
            for entry in entries
            for product_use in products.iq_shots
        ),
    )
    compiled_target = CompiledQuantumTarget(
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
    host_transforms = (DomainHostTransformBinding(products.transform, implementation),)
    return PreparedFakeXCountReference(
        preparation=preparation,
        products=products,
        x_counts=selected_x_counts,
        target=selected_target,
        compiler=compiler,
        calibration_catalog=catalog,
        programs=selected_programs,
        entries=entries,
        compiled_target=compiled_target,
        realization=realization,
        invocation=invocation,
        measurement_mapping=mapping.domain_mapping,
        host_transforms=host_transforms,
    )


def _acquisition_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    selected = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    if len(selected) != 1:
        msg = (
            f"fake X-count entry {entry.id.value!r} requires exactly one "
            f"acquisition for program result {slot_id.value!r}"
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
